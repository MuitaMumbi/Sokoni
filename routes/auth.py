from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from db import get_db
from utils.email_utils import generate_activation_code, send_activation_email
import re

auth_bp = Blueprint("auth", __name__)

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
    
#  POST /api/auth/signup
@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    required = ["username", "email", "phone", "password"]

    # Validate required fields
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    username = data["username"].strip()
    email    = data["email"].strip().lower()
    phone    = data["phone"].strip()
    password = data["password"]

    
    pwd_error = validate_password(password)
    if pwd_error:
        return jsonify({"error": pwd_error}), 400
    db     = get_db()
    cursor = db.cursor(dictionary=True)

    # Check duplicates
    cursor.execute("SELECT user_id FROM users WHERE email=%s OR username=%s", (email, username))
    if cursor.fetchone():
        return jsonify({"error": "Email or username already registered"}), 409

    hashed_pw   = generate_password_hash(password)
    code        = generate_activation_code()
    code_expiry = datetime.utcnow() + timedelta(minutes=30)

    cursor.execute("""
        INSERT INTO users (username, email, phone, password, activation_code, activation_expires)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (username, email, phone, hashed_pw, code, code_expiry))
    db.commit()
    try:
    # Send activation email (non-blocking failure)
        email_sent = send_activation_email(email, username, code)
    except Exception as e:
        current_app.logger.error(f"Failed to send activation email to {email}: {e}")
        email_sent = False
        
    cursor.close()
    return jsonify({
        "message": "Registration successful. Check your email for the activation code.",
        "email_sent": email_sent,
        # Expose code in dev mode only – remove in production
        "activation_code_dev": code if current_app.config["DEBUG"] else None,
    }), 201



#  POST /api/auth/activate
@auth_bp.route("/activate", methods=["POST"])
def activate():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()
    code  = data.get("code", "").strip()

    if not email or not code:
        return jsonify({"error": "Email and activation code are required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT user_id, activation_code, activation_expires, is_active
        FROM users WHERE email=%s
    """, (email,))
    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "User not found"}), 404

    if user["is_active"]:
        return jsonify({"message": "Account already activated"}), 200

    if user["activation_code"] != code:
        return jsonify({"error": "Invalid activation code"}), 400

    if datetime.utcnow() > user["activation_expires"]:
        return jsonify({"error": "Activation code has expired. Request a new one."}), 400

    cursor.execute("""
        UPDATE users
        SET is_active=1, activation_code=NULL, activation_expires=NULL
        WHERE user_id=%s
    """, (user["user_id"],))
    db.commit()
    cursor.close()

    return jsonify({"message": "Account activated successfully. You can now sign in."}), 200


#  POST /api/auth/resend-code
@auth_bp.route("/resend-code", methods=["POST"])
def resend_code():
    data  = request.get_json()
    email = data.get("email", "").strip().lower()

    if not email:
        return jsonify({"error": "Email is required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT user_id, username, is_active FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "User not found"}), 404

    if user["is_active"]:
        return jsonify({"message": "Account already activated"}), 200

    code        = generate_activation_code()
    code_expiry = datetime.utcnow() + timedelta(minutes=30)

    cursor.execute("""
        UPDATE users SET activation_code=%s, activation_expires=%s WHERE user_id=%s
    """, (code, code_expiry, user["user_id"]))
    db.commit()

    email_sent = send_activation_email(email, user["username"], code)
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
        SELECT user_id, username, email, phone, password, is_active, role
        FROM users WHERE email=%s
    """, (email,))
    user = cursor.fetchone()
    cursor.close()

    if not user or not check_password_hash(user["password"], pwd):
        return jsonify({"error": "Invalid email or password"}), 401

    if not user["is_active"]:
        return jsonify({
            "error": "Account not activated. Please check your email for the activation code."
        }), 403

    token = create_access_token(identity=str(user["user_id"]), additional_claims={"role": user["role"]})

    return jsonify({
        "message": "Sign in successful",
        "token": token,
        "user": {
            "user_id":  user["user_id"],
            "username": user["username"],
            "email":    user["email"],
            "phone":    user["phone"],
            "role":     user["role"],
        }
    }), 200


#  GET /api/auth/me  (protected)
@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT user_id, username, email, phone, role, created_at
        FROM users WHERE user_id=%s
    """, (user_id,))
    user = cursor.fetchone()
    cursor.close()

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"user": user}), 200