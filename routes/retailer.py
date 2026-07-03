from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from db import get_db

retailer_bp = Blueprint("retailer", __name__)


def require_retailer():
    claims = get_jwt()
    if claims.get("role") not in ("retailer", "customer"):
        return jsonify({"error": "Retailer access required"}), 403
    return None


# GET /api/retailer/dashboard
@retailer_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def get_dashboard():
    err = require_retailer()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Total orders and total spent
    cursor.execute("""
        SELECT COUNT(*) AS total_orders,
               COALESCE(SUM(total_amount), 0) AS total_spent
        FROM orders
        WHERE user_id = %s
    """, (user_id,))
    order_stats = cursor.fetchone()

    # Orders by status
    cursor.execute("""
        SELECT status, COUNT(*) AS count
        FROM orders
        WHERE user_id = %s
        GROUP BY status
    """, (user_id,))
    status_breakdown = {row["status"]: row["count"] for row in cursor.fetchall()}

    # Active cart
    cursor.execute("""
        SELECT COUNT(*) AS cart_items,
               COALESCE(SUM(c.quantity * p.product_cost), 0) AS cart_total
        FROM cart c
        JOIN products p ON p.product_id = c.product_id
        WHERE c.user_id = %s
    """, (user_id,))
    cart_stats = cursor.fetchone()

    # Loyalty points
    cursor.execute("""
        SELECT COALESCE(SUM(points), 0) AS total_points
        FROM loyalty_points
        WHERE user_id = %s AND is_active = 1
    """, (user_id,))
    loyalty = cursor.fetchone()

    # Recent orders (last 5)
    cursor.execute("""
        SELECT o.order_id, o.total_amount, o.status, o.delivery_city,
               o.created_at, COUNT(oi.item_id) AS items_count
        FROM orders o
        LEFT JOIN order_items oi ON oi.order_id = o.order_id
        WHERE o.user_id = %s
        GROUP BY o.order_id
        ORDER BY o.created_at DESC
        LIMIT 5
    """, (user_id,))
    recent_orders = cursor.fetchall()

    cursor.close()

    return jsonify({
        "stats": {
            "total_orders":  order_stats["total_orders"],
            "total_spent":   float(order_stats["total_spent"]),
            "cart_items":    cart_stats["cart_items"],
            "cart_total":    float(cart_stats["cart_total"]),
            "loyalty_points": int(loyalty["total_points"]),
            "status_breakdown": status_breakdown,
        },
        "recent_orders": recent_orders,
    }), 200


# GET /api/retailer/profile
@retailer_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    err = require_retailer()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT user_id, username, email, phone, business_name,
               country, is_active, created_at
        FROM users WHERE user_id = %s
    """, (user_id,))
    profile = cursor.fetchone()
    cursor.close()

    if not profile:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"profile": profile}), 200


# PUT /api/retailer/profile
@retailer_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    err = require_retailer()
    if err:
        return err

    user_id = get_jwt_identity()
    data = request.get_json() or {}
    updates, vals = [], []

    for field in ("username", "phone", "business_name", "country"):
        if data.get(field) is not None:
            updates.append(f"{field} = %s")
            vals.append(data[field].strip())

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    vals.append(user_id)
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE user_id = %s", vals
    )
    db.commit()
    cursor.close()

    return jsonify({"message": "Profile updated successfully"}), 200


# PATCH /api/retailer/orders/<id>/confirm-delivery
@retailer_bp.route("/orders/<int:order_id>/confirm-delivery", methods=["PATCH"])
@jwt_required()
def confirm_delivery(order_id):
    err = require_retailer()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT order_id, status, total_amount FROM orders
        WHERE order_id = %s AND user_id = %s
    """, (order_id, user_id))
    order = cursor.fetchone()

    if not order:
        return jsonify({"error": "Order not found"}), 404
    if order["status"] != "shipped":
        return jsonify({"error": "Only shipped orders can be confirmed as delivered"}), 400

    # Mark order delivered
    cursor.execute("""
        UPDATE orders SET status = 'delivered' WHERE order_id = %s
    """, (order_id,))

    # Award loyalty points (1 point per KES 100 spent)
    points_earned = int(float(order["total_amount"]) // 100)
    if points_earned > 0:
        cursor.execute("""
            INSERT INTO loyalty_points (user_id, order_id, points, reason)
            VALUES (%s, %s, %s, 'order_delivery')
        """, (user_id, order_id, points_earned))

    db.commit()
    cursor.close()

    return jsonify({
        "message":       "Delivery confirmed",
        "order_id":      order_id,
        "points_earned": points_earned,
    }), 200


# GET /api/retailer/loyalty
@retailer_bp.route("/loyalty", methods=["GET"])
@jwt_required()
def get_loyalty():
    err = require_retailer()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT COALESCE(SUM(points), 0) AS total_points
        FROM loyalty_points
        WHERE user_id = %s AND is_active = 1
    """, (user_id,))
    total = cursor.fetchone()

    cursor.execute("""
        SELECT lp.points, lp.reason, lp.created_at, o.order_id, o.total_amount
        FROM loyalty_points lp
        LEFT JOIN orders o ON o.order_id = lp.order_id
        WHERE lp.user_id = %s
        ORDER BY lp.created_at DESC
        LIMIT 10
    """, (user_id,))
    history = cursor.fetchall()
    cursor.close()

    return jsonify({
        "total_points": int(total["total_points"]),
        "history":      history,
    }), 200