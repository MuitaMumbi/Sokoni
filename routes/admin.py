from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from db import get_db

admin_bp = Blueprint("admin", __name__)


def _require_admin():
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403


# ── GET /api/admin/dashboard ────────────────────────────────────────────────
@admin_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def dashboard():
    err = _require_admin()
    if err: return err

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            COUNT(*)                                                      AS total_orders,
            COALESCE(SUM(total_amount), 0)                                AS total_revenue,
            SUM(CASE WHEN status='pending'   THEN 1 ELSE 0 END)          AS pending_orders,
            SUM(CASE WHEN status='paid'      THEN 1 ELSE 0 END)          AS paid_orders,
            SUM(CASE WHEN status='shipped'   THEN 1 ELSE 0 END)          AS shipped_orders,
            SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END)          AS delivered_orders,
            SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END)          AS cancelled_orders
        FROM orders
    """)
    order_stats = cursor.fetchone()

    cursor.execute("""
        SELECT
            COUNT(*)                                                              AS total_users,
            SUM(CASE WHEN role='supplier' THEN 1 ELSE 0 END)                     AS total_suppliers,
            SUM(CASE WHEN role='retailer' THEN 1 ELSE 0 END)                     AS total_retailers,
            SUM(CASE WHEN role='supplier' AND is_approved=0 THEN 1 ELSE 0 END)   AS pending_suppliers
        FROM users
    """)
    user_stats = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) AS total_products FROM products")
    product_stats = cursor.fetchone()

    cursor.execute("""
        SELECT DATE(created_at) AS date,
               COALESCE(SUM(total_amount), 0) AS revenue,
               COUNT(*) AS orders
        FROM orders
        WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        GROUP BY DATE(created_at)
        ORDER BY date ASC
    """)
    daily_revenue = [
        {**r, "date": str(r["date"]), "revenue": float(r["revenue"])}
        for r in cursor.fetchall()
    ]

    cursor.execute("""
        SELECT p.product_name,
               SUM(oi.quantity) AS units_sold,
               SUM(oi.quantity * oi.unit_price) AS revenue
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        GROUP BY p.product_id, p.product_name
        ORDER BY units_sold DESC
        LIMIT 5
    """)
    top_products = [
        {**r, "revenue": float(r["revenue"])}
        for r in cursor.fetchall()
    ]

    cursor.execute("""
        SELECT o.order_id, o.total_amount, o.status, o.delivery_city, o.country,
               o.created_at, COUNT(oi.item_id) AS items_count,
               COALESCE(u.username, o.buyer_name, 'Guest') AS buyer
        FROM orders o
        LEFT JOIN order_items oi ON o.order_id = oi.order_id
        LEFT JOIN users u ON o.user_id = u.user_id
        GROUP BY o.order_id
        ORDER BY o.created_at DESC
        LIMIT 8
    """)
    recent_orders = cursor.fetchall()

    cursor.close()
    return jsonify({
        "orders":        order_stats,
        "users":         user_stats,
        "products":      product_stats,
        "daily_revenue": daily_revenue,
        "top_products":  top_products,
        "recent_orders": recent_orders,
    }), 200


# ── GET /api/admin/users ─────────────────────────────────────────────────────
@admin_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    err = _require_admin()
    if err: return err

    role   = request.args.get("role", "").strip()
    search = request.args.get("search", "").strip()

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    conditions, params = [], []
    if role:
        conditions.append("role = %s")
        params.append(role)
    if search:
        conditions.append("(username LIKE %s OR email LIKE %s OR business_name LIKE %s)")
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cursor.execute(f"""
        SELECT user_id, username, email, phone, role, business_name,
               country, is_active, is_approved, created_at
        FROM users
        {where}
        ORDER BY created_at DESC
    """, params)

    users = cursor.fetchall()
    cursor.close()
    return jsonify({"users": users}), 200


# ── PATCH /api/admin/users/<id>/toggle-active ────────────────────────────────
@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["PATCH"])
@jwt_required()
def toggle_active(user_id):
    err = _require_admin()
    if err: return err

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT is_active FROM users WHERE user_id=%s", (user_id,))
    user = cursor.fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404

    new_status = 0 if user["is_active"] else 1
    cursor.execute("UPDATE users SET is_active=%s WHERE user_id=%s", (new_status, user_id))
    db.commit()
    cursor.close()

    return jsonify({"is_active": new_status}), 200


# ── DELETE /api/admin/users/<id> ─────────────────────────────────────────────
@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
@jwt_required()
def delete_user(user_id):
    err = _require_admin()
    if err: return err

    db     = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
    db.commit()
    cursor.close()

    return jsonify({"message": "User deleted"}), 200

#  GET /api/admin/suppliers  (admin — list pending suppliers)
@admin_bp.route("/suppliers", methods=["GET"])
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


#  PATCH /api/admin/suppliers/<id>/approve  (admin)
@admin_bp.route("/suppliers/<int:user_id>/approve", methods=["PATCH"])
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
