from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from db import get_db

orders_bp = Blueprint("orders", __name__)


#  POST /api/orders/  — Place order from cart
@orders_bp.route("/", methods=["POST"])
@jwt_required()
def place_order():
    user_id = get_jwt_identity()
    data    = request.get_json() or {}
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    delivery_address = data.get("delivery_address", "").strip()
    delivery_city    = data.get("delivery_city", "").strip()
    country          = data.get("country", "Kenya").strip()

    if not delivery_address or not delivery_city:
        return jsonify({"error": "delivery_address and delivery_city are required"}), 400

    cursor.execute("""
        SELECT c.cart_id, c.product_id, c.quantity,
               p.product_cost, p.stock, p.product_name, p.min_order_qty
        FROM cart c
        JOIN products p ON c.product_id = p.product_id
        WHERE c.user_id = %s
    """, (user_id,))
    cart_items = cursor.fetchall()

    if not cart_items:
        return jsonify({"error": "Cart is empty"}), 400

    for item in cart_items:
        if item["stock"] < item["quantity"]:
            return jsonify({
                "error": f"Insufficient stock for '{item['product_name']}'. Available: {item['stock']}"
            }), 400
        if item["quantity"] < item["min_order_qty"]:
            return jsonify({
                "error": f"Minimum order for '{item['product_name']}' is {item['min_order_qty']}"
            }), 400

    total = sum(float(i["product_cost"]) * i["quantity"] for i in cart_items)

    cursor.execute("""
        INSERT INTO orders (user_id, total_amount, delivery_address, delivery_city, country)
        VALUES (%s, %s, %s, %s, %s)
    """, (user_id, round(total, 2), delivery_address, delivery_city, country))
    db.commit()
    order_id = cursor.lastrowid

    for item in cart_items:
        cursor.execute("""
            INSERT INTO order_items (order_id, product_id, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
        """, (order_id, item["product_id"], item["quantity"], item["product_cost"]))
        cursor.execute("""
            UPDATE products SET stock = stock - %s WHERE product_id = %s
        """, (item["quantity"], item["product_id"]))

    cursor.execute("DELETE FROM cart WHERE user_id=%s", (user_id,))
    db.commit()
    cursor.close()

    return jsonify({
        "message":        "Order placed successfully",
        "order_id":       order_id,
        "total_amount":   round(total, 2),
        "status":         "pending",
        "delivery_city":  delivery_city,
        "country":        country,
    }), 201


#  GET /api/orders/
@orders_bp.route("/", methods=["GET"])
@jwt_required()
def my_orders():
    user_id = get_jwt_identity()
    claims  = get_jwt()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    if claims.get("role") == "admin":
        cursor.execute("""
            SELECT o.order_id, o.total_amount, o.status, o.delivery_city, o.country,
                   o.mpesa_receipt, o.created_at, COUNT(oi.item_id) AS items_count,
                   u.username, u.business_name
            FROM orders o
            LEFT JOIN order_items oi ON o.order_id = oi.order_id
            LEFT JOIN users u ON o.user_id = u.user_id
            GROUP BY o.order_id
            ORDER BY o.created_at DESC
        """)
    else:
        cursor.execute("""
            SELECT o.order_id, o.total_amount, o.status, o.delivery_city, o.country,
                   o.mpesa_receipt, o.created_at, COUNT(oi.item_id) AS items_count
            FROM orders o
            LEFT JOIN order_items oi ON o.order_id = oi.order_id
            WHERE o.user_id = %s
            GROUP BY o.order_id
            ORDER BY o.created_at DESC
        """, (user_id,))

    orders = cursor.fetchall()
    cursor.close()
    return jsonify({"orders": orders}), 200


#  GET /api/orders/<id>
@orders_bp.route("/<int:order_id>", methods=["GET"])
@jwt_required()
def order_detail(order_id):
    user_id = get_jwt_identity()
    claims  = get_jwt()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    if claims.get("role") == "admin":
        cursor.execute("SELECT * FROM orders WHERE order_id=%s", (order_id,))
    else:
        cursor.execute(
            "SELECT * FROM orders WHERE order_id=%s AND user_id=%s",
            (order_id, user_id)
        )

    order = cursor.fetchone()
    if not order:
        return jsonify({"error": "Order not found"}), 404

    cursor.execute("""
        SELECT oi.quantity, oi.unit_price,
               (oi.quantity * oi.unit_price) AS subtotal,
               p.product_id, p.product_name, p.product_photo, p.unit
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        WHERE oi.order_id = %s
    """, (order_id,))

    order["items"] = cursor.fetchall()
    cursor.close()

    return jsonify({"order": order}), 200


#  PATCH /api/orders/<id>/status  (admin)
@orders_bp.route("/<int:order_id>/status", methods=["PATCH"])
@jwt_required()
def update_order_status(order_id):
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

    data   = request.get_json()
    status = data.get("status")
    valid  = {"pending", "paid", "shipped", "delivered", "cancelled"}

    if status not in valid:
        return jsonify({"error": f"Invalid status. Choose from: {', '.join(valid)}"}), 400

    db     = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE orders SET status=%s WHERE order_id=%s", (status, order_id))
    db.commit()
    cursor.close()

    return jsonify({"message": f"Order status updated to '{status}'"}), 200
