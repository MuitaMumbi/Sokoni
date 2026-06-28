import random
import string
import uuid
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from db import get_db
from utils.email_utils import send_activation_email, generate_activation_code, send_reset_email   
import re
from utils.validators import (
    is_valid_email, is_valid_phone, is_valid_username, is_strong_password, sanitize_string
)
import logging
import secrets

auth_bp = Blueprint("auth", __name__)
logger  = logging.getLogger("sokoni") #Your logs are separated from Flask's own logs, SQLAlchemy logs, library warnings etc. You can control your app's log level independently

VALID_ROLES    = {"retailer", "supplier", "admin"}
VALID_COUNTRIES = {"Kenya", "Tanzania", "Uganda", "Rwanda", "Ethiopia"}

def validate_password(password):
        if len(password) < 8:
            return "Password must be at least 8 characters"
        if not re.search(r"[A-Z]", password):
            return "Password must contain at least one uppercase letter"
        if not re.search(r"[0-9]", password):
            return "Password must contain at least one number"
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return "Password must contain at least one special character"
        return None




def generate_activation_code():
    return str(random.randint(100000, 999999))


# ─────────────────────────────────────────────
#  POST /api/auth/signup
# ─────────────────────────────────────────────
@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()

    username      = data.get("username", "").strip()
    email         = data.get("email", "").strip().lower()
    phone         = data.get("phone", "").strip()
    password      = data.get("password", "")
    role          = data.get("role", "retailer").strip().lower()
    business_name = data.get("business_name", "").strip() or None
    country       = data.get("country", "").strip()

    # ── Basic validation ──────────────────────────────────────────
    if not all([username, email, password, role]):
        return jsonify({"error": "username, email, password and role are required"}), 400
     # Block admin creation through public signup
    if role == "admin":
        return jsonify({"error": "Admin accounts cannot be created through signup"}), 403
    
    pw_error = validate_password(password)
    if pw_error:
        return jsonify({"error": pw_error}), 400

    if role == "supplier" and not business_name:
        return jsonify({"error": "business_name is required for suppliers"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    # ── Block if email/username already in users OR pending ───────
    cursor.execute(
        "SELECT 1 FROM users WHERE email=%s OR username=%s",
        (email, username)
    )
    if cursor.fetchone():
        cursor.close()
        return jsonify({"error": "Email or username already registered"}), 409

    cursor.execute(
        "SELECT 1 FROM pending_registrations WHERE email=%s OR username=%s",
        (email, username)
    )
    if cursor.fetchone():
        cursor.close()
        return jsonify({
            "error": "A pending registration already exists for this email or username. "
                     "Check your inbox or request a new code."
        }), 409

    # ── Prepare credentials ───────────────────────────────────────
    hashed_pw   = generate_password_hash(password)
    code        = generate_activation_code()
    code_expiry = datetime.utcnow() + timedelta(minutes=30)
    is_approved = 0 if role == "supplier" else 1

    # ── Send email FIRST — do not touch users table yet ──────────
    try:
        email_sent = send_activation_email(email, username, code)
        if not email_sent:
            cursor.close()
            return jsonify({
                "error": "Failed to send activation email. Please check your email address or try again later."
            }), 500
    except Exception as e:
        current_app.logger.error(f"[SIGNUP] Email sending crashed: {e}")
        cursor.close()
        return jsonify({
            "error": "Failed to send activation email. Please try again later."
        }), 500

    # ── Save to pending_registrations, NOT users ──────────────────
    cursor.execute("""
        INSERT INTO pending_registrations
            (username, email, phone, password, role, business_name,
             country, is_approved, activation_code, activation_expires)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            username           = VALUES(username),
            phone              = VALUES(phone),
            password           = VALUES(password),
            role               = VALUES(role),
            business_name      = VALUES(business_name),
            country            = VALUES(country),
            is_approved        = VALUES(is_approved),
            activation_code    = VALUES(activation_code),
            activation_expires = VALUES(activation_expires)
    """, (username, email, phone, hashed_pw, role, business_name,
          country, is_approved, code, code_expiry))
    db.commit()
    cursor.close()

    msg = (
        "Registration successful. Verify your email, then wait for admin approval."
        if role == "supplier"
        else "Registration successful. Check your email for the activation code."
    )

    return jsonify({
        "message": msg,
        "activation_code_dev": code if current_app.config["DEBUG"] else None,
    }), 201


# ─────────────────────────────────────────────
#  POST /api/auth/activate
# ─────────────────────────────────────────────
@auth_bp.route("/activate", methods=["POST"])
def activate():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    code  = data.get("code", "").strip()

    if not email or not code:
        return jsonify({"error": "Email and activation code are required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    # ── Check pending_registrations, not users ────────────────────
    cursor.execute("""
        SELECT * FROM pending_registrations WHERE email=%s
    """, (email,))
    pending = cursor.fetchone()

    if not pending:
        # Maybe they already activated — check users table
        cursor.execute("SELECT 1 FROM users WHERE email=%s", (email,))
        if cursor.fetchone():
            cursor.close()
            return jsonify({"message": "Account already activated. You can sign in."}), 200
        cursor.close()
        return jsonify({"error": "No pending registration found for this email."}), 404

    if pending["activation_code"] != code:
        cursor.close()
        return jsonify({"error": "Invalid activation code."}), 400

    if datetime.utcnow() > pending["activation_expires"]:
        cursor.close()
        return jsonify({
            "error": "Activation code has expired. Request a new one."
        }), 400

    # ── Code is valid — now insert into users ─────────────────────
    cursor.execute("""
        INSERT INTO users
            (username, email, phone, password, role, business_name,
             country, is_approved, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
    """, (
        pending["username"], pending["email"], pending["phone"],
        pending["password"], pending["role"], pending["business_name"],
        pending["country"], pending["is_approved"]
    ))

    # ── Clean up pending record ───────────────────────────────────
    cursor.execute(
        "DELETE FROM pending_registrations WHERE email=%s", (email,)
    )
    db.commit()
    cursor.close()

    return jsonify({
        "message": "Account activated successfully. You can now sign in."
    }), 200


#  POST /api/auth/resend-code
@auth_bp.route("/resend-code", methods=["POST"])
def resend_code():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Email is required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT username FROM pending_registrations WHERE email=%s", (email,)
    )
    pending = cursor.fetchone()

    if not pending:
        cursor.execute("SELECT 1 FROM users WHERE email=%s", (email,))
        if cursor.fetchone():
            cursor.close()
            return jsonify({"message": "Account already activated. You can sign in."}), 200
        cursor.close()
        return jsonify({"error": "No pending registration found for this email."}), 404

    code        = generate_activation_code()
    code_expiry = datetime.utcnow() + timedelta(minutes=30)

    # ── Update code in pending_registrations ──────────────────────
    cursor.execute("""
        UPDATE pending_registrations
        SET activation_code=%s, activation_expires=%s
        WHERE email=%s
    """, (code, code_expiry, email))
    db.commit()

    # ── Send email AFTER updating the record ─────────────────────
    try:
        email_sent = send_activation_email(email, pending["username"], code)
    except Exception as e:
        current_app.logger.error(f"[RESEND] Email sending crashed: {e}")
        email_sent = False

    cursor.close()

    return jsonify({
        "message": "A new activation code has been sent to your email.",
        "email_sent": email_sent,
        "activation_code_dev": code,
    }), 200


#  POST /api/auth/signin
@auth_bp.route("/signin", methods=["POST"])
def signin():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    pwd   = data.get("password", "")
    
    if not email or not pwd:
        return jsonify({"error": "Email and password are required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT user_id, username, email, phone, password,
               is_active, is_approved, role, business_name, country
        FROM users WHERE email=%s
    """, (email,))
    user = cursor.fetchone()
    cursor.close()

    if not user or not check_password_hash(user["password"], pwd):
        return jsonify({"error": "Invalid email or password"}), 401

    if not user["is_active"]:
        return jsonify({"error": "Account not activated. Check your email for the activation code."}), 403

    if not user["is_approved"]:
        return jsonify({"error": "Your supplier account is pending admin approval."}), 403

    token = create_access_token(
        identity=str(user["user_id"]),
        additional_claims={"role": user["role"], "jti": str(uuid.uuid4())}
    )

    return jsonify({
        "message": "Sign in successful",
        "token": token,
        "user": {
            "user_id":       user["user_id"],
            "username":      user["username"],
            "email":         user["email"],
            "phone":         user["phone"],
            "role":          user["role"],
            "business_name": user["business_name"],
            "country":       user["country"],
        }
    }), 200

#  POST /api/auth/forgot-password
@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Email is required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT user_id, username, is_active FROM users WHERE email=%s", (email,)
    )
    user = cursor.fetchone()

    # Don't reveal whether the email exists or not — security best practice
    if not user or not user["is_active"]:
        cursor.close()
        return jsonify({
            "message": "If that email is registered, a reset link has been sent."
        }), 200

    # Generate a secure random token
    reset_token  = secrets.token_urlsafe(32)
    token_expiry = datetime.utcnow() + timedelta(minutes=30)

    cursor.execute("""
        UPDATE users
        SET reset_token=%s, reset_token_expires=%s
        WHERE user_id=%s
    """, (reset_token, token_expiry, user["user_id"]))
    db.commit()

    # Send the reset email
    try:
        email_sent = send_reset_email(email, user["username"], reset_token)
        if not email_sent:
            current_app.logger.error(f"[FORGOT PASSWORD] Email failed for {email}")
    except Exception as e:
        current_app.logger.error(f"[FORGOT PASSWORD] Email crashed: {e}")

    cursor.close()

    return jsonify({
        "message": "If that email is registered, a reset link has been sent.",
        "reset_token_dev": reset_token if current_app.config["DEBUG"] else None,
    }), 200


#  POST /api/auth/reset-password
@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    data        = request.get_json()
    email       = data.get("email", "").strip().lower()
    token       = data.get("token", "").strip()
    new_password = data.get("new_password", "")

    if not all([email, token, new_password]):
        return jsonify({"error": "email, token and new_password are required"}), 400

    pw_error = validate_password(new_password)
    if pw_error:
        return jsonify({"error": pw_error}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT user_id, reset_token, reset_token_expires
        FROM users WHERE email=%s
    """, (email,))
    user = cursor.fetchone()

    if not user or user["reset_token"] != token:
        cursor.close()
        return jsonify({"error": "Invalid or expired reset token"}), 400

    if datetime.utcnow() > user["reset_token_expires"]:
        cursor.close()
        return jsonify({"error": "Reset token has expired. Request a new one."}), 400

    # Update password and clear the token
    cursor.execute("""
        UPDATE users
        SET password=%s, reset_token=NULL, reset_token_expires=NULL
        WHERE user_id=%s
    """, (generate_password_hash(new_password), user["user_id"]))
    db.commit()
    cursor.close()

    return jsonify({"message": "Password reset successfully. You can now sign in."}), 200

#  POST /api/auth/admin/create  (existing admin only)
@auth_bp.route("/admin/create", methods=["POST"])
@jwt_required()
def create_admin():
    # Only an existing admin can create another admin
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    data     = request.get_json()
    username = data.get("username", "").strip()
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")
    phone    = data.get("phone", "").strip()
    
    if not all([username, email, password, phone]):
        return jsonify({"error": "username, email, password and phone are required"}), 400

    pw_error = validate_password(password)
    if pw_error:
        return jsonify({"error": pw_error}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        "SELECT 1 FROM users WHERE email=%s OR username=%s", (email, username)
    )
    if cursor.fetchone():
        cursor.close()
        return jsonify({"error": "Email or username already registered"}), 409

    hashed_pw = generate_password_hash(password)

    # Admins are inserted directly — no email verification, no pending table
    cursor.execute("""
        INSERT INTO users
            (username, email, password, phone, role, is_active, is_approved)
        VALUES (%s, %s, %s, %s, 'admin', 1, 1)
    """, (username, email, hashed_pw, phone))
    db.commit()
    cursor.close()

    logger.info(f"[ADMIN] New admin account created: {email}")

    return jsonify({"message": f"Admin account created for {username}."}), 201

#  GET /api/auth/me
@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT user_id, username, email, phone, role,
               business_name, country, is_approved, created_at
        FROM users WHERE user_id=%s
    """, (user_id,))
    user = cursor.fetchone()
    cursor.close()

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"user": user}), 200


#  POST /api/auth/check-email  — does this email have an account?
@auth_bp.route("/check-email", methods=["POST"])
def check_email():
    email = (request.get_json() or {}).get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email is required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT user_id, is_active FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()
    cursor.close()

    return jsonify({"exists": bool(user and user["is_active"])}), 200


# POST /api/auth/change-password
@auth_bp.route("/change-password", methods=["POST"])
@jwt_required()
def change_password():
    data         = request.get_json()
    password     = data.get("password", "")
    new_pwd      = data.get("new_password", "")

    if not password or not new_pwd:
        return jsonify({"error": "Both current and new password are required"}), 400

    pw_error = validate_password(new_pwd)
    if pw_error:
        return jsonify({"error": pw_error}), 400

    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("SELECT password FROM users WHERE user_id=%s", (user_id,))
    user = cursor.fetchone()

    if not check_password_hash(user["password"], password):
        cursor.close()
        return jsonify({"error": "Current password is incorrect"}), 401

    cursor.execute(
        "UPDATE users SET password=%s WHERE user_id=%s",
        (generate_password_hash(new_pwd), user_id)
    )
    db.commit()
    cursor.close()

    return jsonify({"message": "Password updated successfully"}), 200

#  POST /api/auth/logout
@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    jti    = get_jwt()["jti"]  # unique ID of the current token
    db     = get_db()
    cursor = db.cursor()

    cursor.execute(
        "INSERT INTO token_blocklist (jti) VALUES (%s)", (jti,)
    )
    db.commit()
    cursor.close()

    return jsonify({"message": "Logged out successfully."}), 200