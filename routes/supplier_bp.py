from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from db import get_db
import cloudinary.uploader
import uuid

supplier_bp = Blueprint("supplier", __name__)


def require_approved_supplier():
    """Ensures the caller is a supplier and is approved."""
    claims = get_jwt()
    if claims.get("role") != "supplier":
        return jsonify({"error": "Supplier access required"}), 403

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT is_approved FROM users WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()

    if not user or not user["is_approved"]:
        return jsonify({"error": "Your account is pending admin approval"}), 403
    return None


# POST /api/supplier/profile  — fill in or update business profile
@supplier_bp.route("/profile", methods=["POST"])
@jwt_required()
def save_profile():
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    is_multipart = request.content_type and "multipart" in request.content_type
    data = request.form if is_multipart else (request.get_json() or {})

    fields = [
        "company_name", "business_reg_number", "kra_pin", "vat_number",
        "contact_person", "phone", "business_address", "warehouse_address",
        "bank_name", "bank_account_number", "bank_account_name",
        "mpesa_number", "mpesa_name",
    ]

    values = {f: (data.get(f) or "").strip() for f in fields}

    # Required fields
    required = ["company_name", "kra_pin", "contact_person", "phone", "business_address"]
    missing = [f for f in required if not values[f]]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # Optional logo upload
    logo_url = None
    if is_multipart and "logo" in request.files:
        file = request.files["logo"]
        if file and file.filename:
            try:
                result = cloudinary.uploader.upload(
                    file,
                    folder="sokoni/logos",
                    public_id=uuid.uuid4().hex,
                    resource_type="image",
                )
                logo_url = result["secure_url"]
            except Exception as e:
                return jsonify({"error": f"Logo upload failed: {str(e)}"}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Check if profile already exists
    cursor.execute("SELECT profile_id FROM supplier_profiles WHERE supplier_id = %s", (user_id,))
    existing = cursor.fetchone()

    if existing:
        # UPDATE
        set_clause = ", ".join([f"{f} = %s" for f in fields])
        params = [values[f] for f in fields]
        if logo_url:
            set_clause += ", logo_url = %s"
            params.append(logo_url)
        set_clause += ", is_complete = 1"
        params.append(user_id)
        cursor.execute(
            f"UPDATE supplier_profiles SET {set_clause} WHERE supplier_id = %s",
            params
        )
    else:
        # INSERT
        col_names = ", ".join(fields) + (", logo_url" if logo_url else "") + ", is_complete, supplier_id"
        placeholders = ", ".join(["%s"] * len(fields)) + (", %s" if logo_url else "") + ", 1, %s"
        params = [values[f] for f in fields]
        if logo_url:
            params.append(logo_url)
        params.append(user_id)
        cursor.execute(
            f"INSERT INTO supplier_profiles ({col_names}) VALUES ({placeholders})",
            params
        )

    db.commit()
    cursor.close()

    return jsonify({"message": "Profile saved successfully"}), 200


# GET /api/supplier/profile
@supplier_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT sp.*, u.email, u.username, u.created_at AS account_created
        FROM supplier_profiles sp
        JOIN users u ON u.user_id = sp.supplier_id
        WHERE sp.supplier_id = %s
    """, (user_id,))
    profile = cursor.fetchone()
    cursor.close()

    if not profile:
        return jsonify({"profile": None, "is_complete": False}), 200

    return jsonify({"profile": profile, "is_complete": bool(profile["is_complete"])}), 200