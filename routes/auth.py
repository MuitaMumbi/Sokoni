import random
import string
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from db import get_db
from utils.email_utils import send_activation_email, generate_activation_code   
import re
from utils.validators import (
    is_valid_email, is_valid_phone, is_valid_username, is_strong_password, sanitize_string
)
import logging

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


# ─────────────────────────────────────────────
#  POST /api/auth/resend-code
# ─────────────────────────────────────────────
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
        "activation_code_dev": code if current_app.config["DEBUG"] else None,
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
        additional_claims={"role": user["role"]}
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


#  POST /api/auth/retailer-send-code  — send activation code, create placeholder if needed
@auth_bp.route("/retailer-send-code", methods=["POST"])
def retailer_send_code():
    email = (request.get_json() or {}).get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email is required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT user_id, username, is_active FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()

    if user and user["is_active"]:
        cursor.close()
        return jsonify({"error": "An account with this email already exists. Please sign in."}), 409

    code        = generate_activation_code()
    code_expiry = datetime.utcnow() + timedelta(minutes=30)

    if user:
        cursor.execute(
            "UPDATE users SET activation_code=%s, activation_expires=%s WHERE user_id=%s",
            (code, code_expiry, user["user_id"])
        )
        username = user["username"]
    else:
        # Create a lightweight placeholder — details filled in at retailer-signup
        username = email.split("@")[0] + "_" + "".join(random.choices(string.digits, k=4))
        hashed_pw = generate_password_hash("".join(random.choices(string.ascii_letters, k=16)))
        cursor.execute("""
            INSERT INTO users
                (username, email, phone, password, role, is_approved, is_active,
                 activation_code, activation_expires)
            VALUES (%s, %s, '', %s, 'retailer', 1, 0, %s, %s)
        """, (username, email, hashed_pw, code, code_expiry))

    db.commit()
    email_sent = send_activation_email(email, username, code)
    cursor.close()

    return jsonify({
        "message":             f"Activation code sent to {email}.",
        "email_sent":          email_sent,
        "activation_code_dev": code if current_app.config["DEBUG"] else None,
    }), 200


#  POST /api/auth/retailer-signup  — verify code, set password, link past orders
@auth_bp.route("/retailer-signup", methods=["POST"])
def retailer_signup():
    data     = request.get_json() or {}
    email    = data.get("email", "").strip().lower()
    code     = data.get("code", "").strip()
    password = data.get("password", "")
    name     = data.get("name", "").strip()
    phone    = data.get("phone", "").strip()

    if not all([email, code, password, name, phone]):
        return jsonify({"error": "All fields are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT user_id, activation_code, activation_expires
        FROM users WHERE email=%s
    """, (email,))
    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "No pending account for this email. Request a code first."}), 404
    if user["activation_code"] != code:
        return jsonify({"error": "Invalid activation code"}), 400
    if datetime.utcnow() > user["activation_expires"]:
        return jsonify({"error": "Code has expired. Request a new one."}), 400

    hashed_pw = generate_password_hash(password)
    # Use name as username if unique, else append random digits
    username = name.replace(" ", "").lower()
    cursor.execute("SELECT user_id FROM users WHERE username=%s AND user_id != %s", (username, user["user_id"]))
    if cursor.fetchone():
        username = username + "_" + "".join(random.choices(string.digits, k=4))

    cursor.execute("""
        UPDATE users
        SET username=%s, phone=%s, password=%s,
            is_active=1, activation_code=NULL, activation_expires=NULL
        WHERE user_id=%s
    """, (username, phone, hashed_pw, user["user_id"]))

    # Link all past guest orders placed with this email
    cursor.execute("""
        UPDATE orders SET user_id=%s
        WHERE buyer_email=%s AND user_id IS NULL
    """, (user["user_id"], email))

    db.commit()

    token = create_access_token(
        identity=str(user["user_id"]),
        additional_claims={"role": "retailer"}
    )

    cursor.close()
    return jsonify({
        "message": "Account created successfully.",
        "token": token,
        "user": {
            "user_id":       user["user_id"],
            "username":      username,
            "email":         email,
            "phone":         phone,
            "role":          "retailer",
            "business_name": None,
            "country":       "Kenya",
        }
    }), 201


#  GET /api/auth/suppliers  (admin — list pending suppliers)
@auth_bp.route("/suppliers", methods=["GET"])
@jwt_required()
def list_suppliers():
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    db     = get_db()
    cursor = db.cursor(dictionary=True)
    approved = request.args.get("approved")

    if approved == "0":
        cursor.execute("""
            SELECT user_id, username, email, phone, business_name, country, created_at
            FROM users WHERE role='supplier' AND is_approved=0
        """)
    else:
        cursor.execute("""
            SELECT user_id, username, email, phone, business_name, country, is_approved, created_at
            FROM users WHERE role='supplier'
        """)

    suppliers = cursor.fetchall()
    cursor.close()
    return jsonify({"suppliers": suppliers}), 200


#  PATCH /api/auth/suppliers/<id>/approve  (admin)
@auth_bp.route("/suppliers/<int:user_id>/approve", methods=["PATCH"])
@jwt_required()
def approve_supplier(user_id):
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT user_id, role FROM users WHERE user_id=%s", (user_id,))
    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "User not found"}), 404
    if user["role"] != "supplier":
        return jsonify({"error": "User is not a supplier"}), 400

    cursor.execute("UPDATE users SET is_approved=1 WHERE user_id=%s", (user_id,))
    db.commit()
    cursor.close()

    return jsonify({"message": "Supplier approved successfully"}), 200
