from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from db import get_db

supplier_bp = Blueprint("supplier", __name__)


def require_supplier():
    claims = get_jwt()
    if claims.get("role") not in ("supplier", "admin"):
        return jsonify({"error": "Supplier access required"}), 403
    return None


#  GET /api/supplier/dashboard
@supplier_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def dashboard():
    err = require_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS total FROM products WHERE created_by=%s", (user_id,))
    product_count = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COUNT(DISTINCT o.order_id) AS total
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p ON oi.product_id = p.product_id
        WHERE p.created_by = %s AND o.status IN ('pending','paid')
    """, (user_id,))
    active_orders = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS revenue
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        JOIN orders o ON oi.order_id = o.order_id
        WHERE p.created_by = %s AND o.status IN ('shipped','delivered')
    """, (user_id,))
    revenue = float(cursor.fetchone()["revenue"])

    cursor.execute("""
        SELECT COUNT(DISTINCT o.order_id) AS total
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p ON oi.product_id = p.product_id
        WHERE p.created_by = %s AND o.status = 'pending'
    """, (user_id,))
    pending_orders = cursor.fetchone()["total"]

    cursor.close()
    return jsonify({
        "product_count":  product_count,
        "active_orders":  active_orders,
        "pending_orders": pending_orders,
        "revenue":        round(revenue, 2),
    }), 200


#  GET /api/supplier/products
@supplier_bp.route("/products", methods=["GET"])
@jwt_required()
def my_products():
    err = require_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.product_id, p.product_name, p.product_cost, p.stock,
               p.min_order_qty, p.unit, p.country, p.created_at,
               c.name AS category
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.category_id
        WHERE p.created_by = %s
        ORDER BY p.created_at DESC
    """, (user_id,))

    products = cursor.fetchall()
    cursor.close()
    return jsonify({"products": products}), 200


#  GET /api/supplier/orders
@supplier_bp.route("/orders", methods=["GET"])
@jwt_required()
def supplier_orders():
    err = require_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    # Distinct orders that contain at least one of this supplier's products
    cursor.execute("""
        SELECT DISTINCT o.order_id, o.status, o.delivery_city, o.country,
               o.created_at, u.username, u.business_name,
               (
                   SELECT SUM(oi2.quantity * oi2.unit_price)
                   FROM order_items oi2
                   JOIN products p2 ON oi2.product_id = p2.product_id
                   WHERE oi2.order_id = o.order_id AND p2.created_by = %s
               ) AS supplier_total
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p ON oi.product_id = p.product_id
        JOIN users u ON o.user_id = u.user_id
        WHERE p.created_by = %s
        ORDER BY o.created_at DESC
    """, (user_id, user_id))
    orders = cursor.fetchall()

    # For each order, attach the supplier's line items
    for order in orders:
        cursor.execute("""
            SELECT oi.item_id, oi.quantity, oi.unit_price,
                   (oi.quantity * oi.unit_price) AS subtotal,
                   p.product_id, p.product_name, p.unit
            FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            WHERE oi.order_id = %s AND p.created_by = %s
        """, (order["order_id"], user_id))
        order["items"] = cursor.fetchall()

    cursor.close()
    return jsonify({"orders": orders}), 200


#  PATCH /api/supplier/orders/<order_id>/ship  — mark order as shipped
@supplier_bp.route("/orders/<int:order_id>/ship", methods=["PATCH"])
@jwt_required()
def ship_order(order_id):
    err = require_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    # Verify this supplier has items in this order
    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        WHERE oi.order_id = %s AND p.created_by = %s
    """, (order_id, user_id))
    if cursor.fetchone()["cnt"] == 0:
        return jsonify({"error": "Order not found"}), 404

    cursor.execute("SELECT status FROM orders WHERE order_id=%s", (order_id,))
    order = cursor.fetchone()
    if not order:
        return jsonify({"error": "Order not found"}), 404
    if order["status"] not in ("paid", "pending"):
        return jsonify({"error": f"Cannot ship an order with status '{order['status']}'"}), 400

    cursor.execute("UPDATE orders SET status='shipped' WHERE order_id=%s", (order_id,))
    db.commit()
    cursor.close()

    return jsonify({"message": "Order marked as shipped"}), 200
