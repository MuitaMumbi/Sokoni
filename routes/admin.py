from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from db import get_db
from routes.auth import validate_password 
from werkzeug.security import generate_password_hash

admin_bp = Blueprint("admin", __name__)


def _require_admin():
    if get_jwt().get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403


# ── GET /api/admin/dashboard
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


# GET /api/admin/users 
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

#  POST /api/admin/create-admin  (admin — create another admin account)
@admin_bp.route("/create-admin", methods=["POST"])
@jwt_required()
def create_admin():
    err = _require_admin()
    if err: return err

    data     = request.get_json()
    username = data.get("username", "").strip()
    email    = data.get("email", "").strip().lower()
    phone    = data.get("phone", "").strip()
    password = data.get("password", "")

    if not all([username, email, password]):
        return jsonify({"error": "username, email and password are required"}), 400

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
        return jsonify({"error": "Email or username already exists"}), 409

    cursor.execute("""
        INSERT INTO users
            (username, email, phone, password, role, is_active, is_approved)
        VALUES (%s, %s, %s, %s, 'admin', 1, 1)
    """, (username, email, phone or "", generate_password_hash(password)))
    db.commit()
    cursor.close()

    return jsonify({"message": f"Admin account created for {username}"}), 201


# POST /api/admin/purchase-orders — raise a PO against a supplier
@admin_bp.route("/purchase-orders", methods=["POST"])
@jwt_required()
def create_purchase_order():
    err = _require_admin()
    if err:
        return err

    from flask_jwt_extended import get_jwt_identity
    admin_id = get_jwt_identity()

    data               = request.get_json() or {}
    supplier_id        = data.get("supplier_id")
    product_id         = data.get("product_id")
    quantity_requested = data.get("quantity_requested")

    if not all([supplier_id, product_id, quantity_requested]):
        return jsonify({"error": "supplier_id, product_id and quantity_requested are required"}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Confirm supplier exists and is approved
    cursor.execute("""
        SELECT user_id FROM users
        WHERE user_id = %s AND role = 'supplier' AND is_approved = 1
    """, (supplier_id,))
    if not cursor.fetchone():
        return jsonify({"error": "Supplier not found or not approved"}), 404

    # Confirm product belongs to this supplier
    cursor.execute("""
        SELECT product_id FROM products
        WHERE product_id = %s AND created_by = %s
    """, (product_id, supplier_id))
    if not cursor.fetchone():
        return jsonify({"error": "Product not found or does not belong to this supplier"}), 404

    cursor.execute("""
        INSERT INTO purchase_orders
            (product_id, supplier_id, quantity_requested, status, requested_by, auto_generated)
        VALUES (%s, %s, %s, 'pending', %s, 0)
    """, (product_id, supplier_id, int(quantity_requested), admin_id))
    db.commit()
    po_id = cursor.lastrowid

    # Notify the supplier
    cursor.execute("""
        INSERT INTO notifications (user_id, title, message, type)
        VALUES (%s, %s, %s, 'po_created')
    """, (
        supplier_id,
        "New Purchase Order",
        f"A new purchase order #{po_id} has been raised for {quantity_requested} units. Please review and respond.",
    ))
    db.commit()
    cursor.close()

    return jsonify({"message": "Purchase order created", "po_id": po_id}), 201


# GET /api/admin/purchase-orders — list all POs
@admin_bp.route("/purchase-orders", methods=["GET"])
@jwt_required()
def list_purchase_orders():
    err = _require_admin()
    if err:
        return err

    db = get_db()
    cursor = db.cursor(dictionary=True)

    status = request.args.get("status")
    page   = max(1, int(request.args.get("page", 1)))
    limit  = min(100, int(request.args.get("limit", 20)))
    offset = (page - 1) * limit

    filters = []
    params  = []

    if status:
        filters.append("po.status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    cursor.execute(f"""
        SELECT po.po_id, po.quantity_requested, po.status,
               po.auto_generated, po.created_at, po.updated_at,
               p.product_name, p.unit,
               u.username AS supplier_name, u.business_name
        FROM purchase_orders po
        JOIN products p ON p.product_id = po.product_id
        JOIN users u ON u.user_id = po.supplier_id
        {where}
        ORDER BY po.created_at DESC
        LIMIT %s OFFSET %s
    """, params + [limit, offset])
    orders = cursor.fetchall()

    cursor.execute(f"""
        SELECT COUNT(*) AS total FROM purchase_orders po {where}
    """, params)
    total = cursor.fetchone()["total"]
    cursor.close()

    return jsonify({
        "purchase_orders": orders,
        "total": total,
        "page":  page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }), 200


# GET /api/admin/deliveries — list all deliveries
@admin_bp.route("/deliveries", methods=["GET"])
@jwt_required()
def list_deliveries():
    err = _require_admin()
    if err:
        return err

    db = get_db()
    cursor = db.cursor(dictionary=True)

    status = request.args.get("status")
    page   = max(1, int(request.args.get("page", 1)))
    limit  = min(100, int(request.args.get("limit", 20)))
    offset = (page - 1) * limit

    filters = []
    params  = []

    if status:
        filters.append("d.status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    cursor.execute(f"""
        SELECT d.delivery_id, d.quantity_delivered, d.status,
               d.delivery_date, d.created_at,
               po.po_id, po.quantity_requested,
               p.product_name, p.unit,
               u.username AS supplier_name, u.business_name
        FROM deliveries d
        JOIN purchase_orders po ON po.po_id = d.po_id
        JOIN products p ON p.product_id = po.product_id
        JOIN users u ON u.user_id = po.supplier_id
        {where}
        ORDER BY d.created_at DESC
        LIMIT %s OFFSET %s
    """, params + [limit, offset])
    deliveries = cursor.fetchall()

    cursor.execute(f"""
        SELECT COUNT(*) AS total
        FROM deliveries d
        JOIN purchase_orders po ON po.po_id = d.po_id
        {where}
    """, params)
    total = cursor.fetchone()["total"]
    cursor.close()

    return jsonify({
        "deliveries": deliveries,
        "total": total,
        "page":  page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }), 200


# PATCH /api/admin/deliveries/<id>/confirm — confirm receipt, create invoice
@admin_bp.route("/deliveries/<int:delivery_id>/confirm", methods=["PATCH"])
@jwt_required()
def confirm_delivery(delivery_id):
    err = _require_admin()
    if err:
        return err

    from flask_jwt_extended import get_jwt_identity
    admin_id = get_jwt_identity()

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT d.*, po.supplier_id, po.product_id, po.quantity_requested
        FROM deliveries d
        JOIN purchase_orders po ON po.po_id = d.po_id
        WHERE d.delivery_id = %s
    """, (delivery_id,))
    delivery = cursor.fetchone()

    if not delivery:
        return jsonify({"error": "Delivery not found"}), 404

    if delivery["status"] == "delivered":
        return jsonify({"error": "Delivery already confirmed"}), 400

    data           = request.get_json() or {}
    amount         = data.get("amount")
    due_date       = data.get("due_date")

    if not amount:
        return jsonify({"error": "amount is required to generate invoice"}), 400

    # Confirm delivery
    cursor.execute("""
        UPDATE deliveries SET status = 'delivered', received_by = %s
        WHERE delivery_id = %s
    """, (admin_id, delivery_id))

    # Update inventory
    cursor.execute("""
        UPDATE inventory SET quantity = quantity + %s
        WHERE product_id = %s AND supplier_id = %s
    """, (delivery["quantity_delivered"], delivery["product_id"], delivery["supplier_id"]))

    # Sync products.stock
    cursor.execute("""
        UPDATE products SET stock = stock + %s WHERE product_id = %s
    """, (delivery["quantity_delivered"], delivery["product_id"]))

    # Create invoice
    cursor.execute("""
        INSERT INTO invoices (supplier_id, delivery_id, amount, status, due_date)
        VALUES (%s, %s, %s, 'unpaid', %s)
    """, (delivery["supplier_id"], delivery_id, float(amount), due_date))
    db.commit()
    invoice_id = cursor.lastrowid

    # Notify supplier
    cursor.execute("""
        INSERT INTO notifications (user_id, title, message, type)
        VALUES (%s, %s, %s, 'shipment_received')
    """, (
        delivery["supplier_id"],
        "Delivery Confirmed",
        f"Your delivery #{delivery_id} has been received. Invoice #{invoice_id} of KES {amount} has been generated.",
    ))
    db.commit()
    cursor.close()

    return jsonify({
        "message":    "Delivery confirmed and invoice generated",
        "invoice_id": invoice_id,
        "delivery_id": delivery_id,
    }), 200


# GET /api/admin/invoices — list all invoices
@admin_bp.route("/invoices", methods=["GET"])
@jwt_required()
def list_invoices():
    err = _require_admin()
    if err:
        return err

    db = get_db()
    cursor = db.cursor(dictionary=True)

    status = request.args.get("status")
    page   = max(1, int(request.args.get("page", 1)))
    limit  = min(100, int(request.args.get("limit", 20)))
    offset = (page - 1) * limit

    filters = []
    params  = []

    if status:
        filters.append("i.status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    cursor.execute(f"""
        SELECT i.invoice_id, i.amount, i.status, i.due_date, i.paid_at, i.created_at,
               u.username AS supplier_name, u.business_name,
               d.delivery_id, d.quantity_delivered
        FROM invoices i
        JOIN users u ON u.user_id = i.supplier_id
        JOIN deliveries d ON d.delivery_id = i.delivery_id
        {where}
        ORDER BY i.created_at DESC
        LIMIT %s OFFSET %s
    """, params + [limit, offset])
    invoices = cursor.fetchall()

    cursor.execute(f"SELECT COUNT(*) AS total FROM invoices i {where}", params)
    total = cursor.fetchone()["total"]
    cursor.close()

    return jsonify({
        "invoices": invoices,
        "total": total,
        "page":  page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }), 200


# PATCH /api/admin/invoices/<id>/pay — mark invoice as paid
@admin_bp.route("/invoices/<int:invoice_id>/pay", methods=["PATCH"])
@jwt_required()
def mark_invoice_paid(invoice_id):
    err = _require_admin()
    if err:
        return err

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM invoices WHERE invoice_id = %s", (invoice_id,))
    invoice = cursor.fetchone()

    if not invoice:
        return jsonify({"error": "Invoice not found"}), 404
    if invoice["status"] == "paid":
        return jsonify({"error": "Invoice already paid"}), 400

    cursor.execute("""
        UPDATE invoices SET status = 'paid', paid_at = NOW()
        WHERE invoice_id = %s
    """, (invoice_id,))

    # Notify supplier
    cursor.execute("""
        INSERT INTO notifications (user_id, title, message, type)
        VALUES (%s, %s, %s, 'payment_completed')
    """, (
        invoice["supplier_id"],
        "Payment Received",
        f"Invoice #{invoice_id} of KES {invoice['amount']} has been marked as paid.",
    ))
    db.commit()
    cursor.close()

    return jsonify({"message": "Invoice marked as paid", "invoice_id": invoice_id}), 200