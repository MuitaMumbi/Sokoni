from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from db import get_db

promos_bp = Blueprint("promos", __name__)


def _require_admin():
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
    return None


def _apply_promo(code, cart_total, cursor):
    """Validate a promo code and return discount_amount, or raise ValueError."""
    code = code.strip().upper()
    cursor.execute(
        "SELECT * FROM promo_codes WHERE code=%s AND is_active=1", (code,)
    )
    promo = cursor.fetchone()
    if not promo:
        raise ValueError("Invalid or inactive promo code")
    if promo["expires_at"] and promo["expires_at"] < datetime.utcnow():
        raise ValueError("Promo code has expired")
    if promo["max_uses"] is not None and promo["used_count"] >= promo["max_uses"]:
        raise ValueError("Promo code has reached its usage limit")
    if cart_total < float(promo["min_order_amount"] or 0):
        raise ValueError(
            f"Minimum order of KES {float(promo['min_order_amount']):,.0f} required"
        )
    if promo["type"] == "percent":
        discount = round(cart_total * float(promo["value"]) / 100, 2)
    else:
        discount = min(round(float(promo["value"]), 2), cart_total)
    return promo["promo_id"], discount


# POST /api/promos/validate  — public, called from cart before placing order
@promos_bp.route("/validate", methods=["POST"])
def validate_promo():
    data       = request.get_json() or {}
    code       = (data.get("code") or "").strip().upper()
    cart_total = float(data.get("cart_total", 0))

    if not code:
        return jsonify({"error": "Code is required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        _, discount = _apply_promo(code, cart_total, cursor)
    except ValueError as e:
        cursor.close()
        return jsonify({"error": str(e)}), 400
    finally:
        cursor.close()

    return jsonify({
        "valid":           True,
        "code":            code,
        "discount_amount": discount,
        "final_total":     round(cart_total - discount, 2),
    }), 200


# GET /api/promos/  (admin)
@promos_bp.route("/", methods=["GET"])
@jwt_required()
def list_promos():
    err = _require_admin()
    if err:
        return err
    db     = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM promo_codes ORDER BY created_at DESC")
    promos = cursor.fetchall()
    cursor.close()
    return jsonify({"promos": promos}), 200


# POST /api/promos/  (admin)
@promos_bp.route("/", methods=["POST"])
@jwt_required()
def create_promo():
    err = _require_admin()
    if err:
        return err
    data      = request.get_json() or {}
    code      = (data.get("code") or "").strip().upper()
    promo_type = data.get("type", "percent")
    value     = data.get("value")
    if not code or value is None:
        return jsonify({"error": "code and value are required"}), 400
    if promo_type not in ("percent", "flat"):
        return jsonify({"error": "type must be percent or flat"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT promo_id FROM promo_codes WHERE code=%s", (code,))
    if cursor.fetchone():
        cursor.close()
        return jsonify({"error": "Code already exists"}), 409

    cursor.execute("""
        INSERT INTO promo_codes (code, type, value, min_order_amount, max_uses, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        code, promo_type, float(value),
        float(data.get("min_order_amount", 0)),
        data.get("max_uses") or None,
        data.get("expires_at") or None,
    ))
    db.commit()
    promo_id = cursor.lastrowid
    cursor.close()
    return jsonify({"message": "Promo code created", "promo_id": promo_id}), 201


# PUT /api/promos/<id>  (admin)
@promos_bp.route("/<int:promo_id>", methods=["PUT"])
@jwt_required()
def update_promo(promo_id):
    err = _require_admin()
    if err:
        return err
    data         = request.get_json() or {}
    updates, vals = [], []
    for field in ("code", "type", "expires_at"):
        if data.get(field) is not None:
            updates.append(f"{field}=%s"); vals.append(data[field])
    if data.get("value") is not None:
        updates.append("value=%s"); vals.append(float(data["value"]))
    if data.get("min_order_amount") is not None:
        updates.append("min_order_amount=%s"); vals.append(float(data["min_order_amount"]))
    if data.get("max_uses") is not None:
        updates.append("max_uses=%s"); vals.append(int(data["max_uses"]))
    if data.get("is_active") is not None:
        updates.append("is_active=%s"); vals.append(1 if data["is_active"] else 0)
    if not updates:
        return jsonify({"error": "Nothing to update"}), 400
    vals.append(promo_id)
    db     = get_db()
    cursor = db.cursor()
    cursor.execute(f"UPDATE promo_codes SET {', '.join(updates)} WHERE promo_id=%s", vals)
    db.commit()
    cursor.close()
    return jsonify({"message": "Promo updated"}), 200


# DELETE /api/promos/<id>  (admin)
@promos_bp.route("/<int:promo_id>", methods=["DELETE"])
@jwt_required()
def delete_promo(promo_id):
    err = _require_admin()
    if err:
        return err
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM promo_codes WHERE promo_id=%s", (promo_id,))
    db.commit()
    cursor.close()
    return jsonify({"message": "Promo deleted"}), 200
