from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from db import get_db
import cloudinary.uploader
import uuid
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
supplier_bp = Blueprint("supplier", __name__)

# Helper function to check if the user is an approved supplier
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


# GET /api/supplier/dashboard
@supplier_bp.route("/dashboard", methods=["GET"])
@jwt_required()
def get_dashboard():
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Total products this supplier has listed
    cursor.execute("""
        SELECT COUNT(*) AS total_products FROM products
        WHERE created_by = %s
    """, (user_id,))
    total_products = cursor.fetchone()["total_products"]

    # Active products (in stock)
    cursor.execute("""
        SELECT COUNT(*) AS active_products FROM products
        WHERE created_by = %s AND stock > 0
    """, (user_id,))
    active_products = cursor.fetchone()["active_products"]

    # Low stock products (stock > 0 but below threshold in inventory)
    cursor.execute("""
        SELECT COUNT(*) AS low_stock FROM inventory
        WHERE supplier_id = %s AND quantity <= low_stock_threshold AND quantity > 0
    """, (user_id,))
    low_stock = cursor.fetchone()["low_stock"]

    # Out of stock products
    cursor.execute("""
        SELECT COUNT(*) AS out_of_stock FROM products
        WHERE created_by = %s AND stock = 0
    """, (user_id,))
    out_of_stock = cursor.fetchone()["out_of_stock"]

    # Pending purchase orders raised against this supplier
    cursor.execute("""
        SELECT COUNT(*) AS pending_pos FROM purchase_orders
        WHERE supplier_id = %s AND status = 'pending'
    """, (user_id,))
    pending_pos = cursor.fetchone()["pending_pos"]

    # Unpaid invoices
    cursor.execute("""
        SELECT COUNT(*) AS unpaid_invoices FROM invoices
        WHERE supplier_id = %s AND status = 'unpaid'
    """, (user_id,))
    unpaid_invoices = cursor.fetchone()["unpaid_invoices"]

    # Total unpaid amount
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) AS unpaid_amount FROM invoices
        WHERE supplier_id = %s AND status = 'unpaid'
    """, (user_id,))
    unpaid_amount = cursor.fetchone()["unpaid_amount"]

    # Recent purchase orders (last 5)
    cursor.execute("""
        SELECT po.po_id, p.product_name, po.quantity_requested,
               po.status, po.created_at
        FROM purchase_orders po
        JOIN products p ON p.product_id = po.product_id
        WHERE po.supplier_id = %s
        ORDER BY po.created_at DESC
        LIMIT 5
    """, (user_id,))
    recent_pos = cursor.fetchall()

    # Recent deliveries (last 5)
    cursor.execute("""
        SELECT d.delivery_id, d.quantity_delivered, d.status,
               d.delivery_date, po.po_id
        FROM deliveries d
        JOIN purchase_orders po ON po.po_id = d.po_id
        WHERE po.supplier_id = %s
        ORDER BY d.created_at DESC
        LIMIT 5
    """, (user_id,))
    recent_deliveries = cursor.fetchall()

    cursor.close()

    return jsonify({
        "stats": {
            "total_products":   total_products,
            "active_products":  active_products,
            "low_stock":        low_stock,
            "out_of_stock":     out_of_stock,
            "pending_pos":      pending_pos,
            "unpaid_invoices":  unpaid_invoices,
            "unpaid_amount":    float(unpaid_amount),
        },
        "recent_purchase_orders": recent_pos,
        "recent_deliveries":      recent_deliveries,
    }), 200

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_image(file, folder="sokoni/products"):
    if not file or not allowed_file(file.filename):
        return None, "Invalid file type. Allowed: png, jpg, jpeg, webp, gif"
    try:
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            public_id=uuid.uuid4().hex,
            resource_type="image",
        )
        return result["secure_url"], None
    except Exception as e:
        return None, f"Image upload failed: {str(e)}"


# GET /api/supplier/products — list own products
@supplier_bp.route("/products", methods=["GET"])
@jwt_required()
def get_supplier_products():
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    page  = max(1, int(request.args.get("page", 1)))
    limit = min(100, int(request.args.get("limit", 20)))
    offset = (page - 1) * limit

    cursor.execute("""
        SELECT p.*, c.name AS category
        FROM products p
        LEFT JOIN categories c ON c.category_id = p.category_id
        WHERE p.created_by = %s
        ORDER BY p.created_at DESC
        LIMIT %s OFFSET %s
    """, (user_id, limit, offset))
    products = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) AS total FROM products WHERE created_by = %s", (user_id,))
    total = cursor.fetchone()["total"]
    cursor.close()

    return jsonify({
        "products": products,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }), 200


# POST /api/supplier/products — add a product
@supplier_bp.route("/products", methods=["POST"])
@jwt_required()
def add_supplier_product():
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    is_multipart = request.content_type and "multipart" in request.content_type
    data = request.form if is_multipart else (request.get_json() or {})

    product_name  = (data.get("product_name") or "").strip()
    product_cost  = data.get("product_cost")
    product_desc  = data.get("product_desc") or ""
    stock         = data.get("stock", 0)
    category_id   = data.get("category_id")
    min_order_qty = data.get("min_order_qty", 1)
    unit          = (data.get("unit") or "piece").strip()
    country       = (data.get("country") or "Kenya").strip()

    if not product_name or product_cost is None:
        return jsonify({"error": "product_name and product_cost are required"}), 400

    try:
        product_cost  = float(product_cost)
        stock         = int(stock)
        min_order_qty = int(min_order_qty)
        category_id   = int(category_id) if category_id else None
    except ValueError:
        return jsonify({"error": "Invalid numeric value"}), 400

    photo_url = None
    if is_multipart and "product_photo" in request.files:
        photo_url, upload_err = upload_image(request.files["product_photo"])
        if upload_err:
            return jsonify({"error": upload_err}), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        INSERT INTO products
            (product_name, product_cost, product_desc, product_photo,
             stock, category_id, min_order_qty, unit, country, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (product_name, product_cost, product_desc, photo_url,
          stock, category_id, min_order_qty, unit, country, user_id))
    db.commit()
    product_id = cursor.lastrowid

    # Auto-create inventory record for this product
    cursor.execute("""
        INSERT INTO inventory (product_id, supplier_id, quantity, low_stock_threshold)
        VALUES (%s, %s, %s, 50)
    """, (product_id, user_id, stock))
    db.commit()
    cursor.close()

    return jsonify({"message": "Product added successfully", "product_id": product_id}), 201


# PUT /api/supplier/products/<id> — edit own product
@supplier_bp.route("/products/<int:product_id>", methods=["PUT"])
@jwt_required()
def update_supplier_product(product_id):
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM products WHERE product_id = %s AND created_by = %s", (product_id, user_id))
    product = cursor.fetchone()
    if not product:
        return jsonify({"error": "Product not found or access denied"}), 404

    is_multipart = request.content_type and "multipart" in request.content_type
    data = request.form if is_multipart else (request.get_json() or {})
    updates, vals = [], []

    for field in ("product_name", "product_desc", "unit", "country"):
        if data.get(field) is not None:
            updates.append(f"{field} = %s"); vals.append(data[field])
    if data.get("product_cost") is not None:
        updates.append("product_cost = %s"); vals.append(float(data["product_cost"]))
    if data.get("stock") is not None:
        updates.append("stock = %s"); vals.append(int(data["stock"]))
    if data.get("min_order_qty") is not None:
        updates.append("min_order_qty = %s"); vals.append(int(data["min_order_qty"]))
    if data.get("category_id") is not None:
        updates.append("category_id = %s"); vals.append(int(data["category_id"]))

    if is_multipart and "product_photo" in request.files:
        file = request.files["product_photo"]
        if file and file.filename:
            photo_url, upload_err = upload_image(file)
            if upload_err:
                return jsonify({"error": upload_err}), 400
            updates.append("product_photo = %s"); vals.append(photo_url)

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    vals.append(product_id)
    cursor.execute(f"UPDATE products SET {', '.join(updates)} WHERE product_id = %s", vals)
    db.commit()
    cursor.close()

    return jsonify({"message": "Product updated successfully"}), 200


# PATCH /api/supplier/products/<id>/archive — deactivate without deleting
@supplier_bp.route("/products/<int:product_id>/archive", methods=["PATCH"])
@jwt_required()
def archive_supplier_product(product_id):
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT product_id, is_active FROM products WHERE product_id = %s AND created_by = %s", (product_id, user_id))
    product = cursor.fetchone()
    if not product:
        return jsonify({"error": "Product not found or access denied"}), 404

    new_status = 0 if product["is_active"] else 1
    cursor.execute("UPDATE products SET is_active = %s WHERE product_id = %s", (new_status, product_id))
    db.commit()
    cursor.close()

    label = "archived" if new_status == 0 else "restored"
    return jsonify({"message": f"Product {label} successfully"}), 200


# DELETE /api/supplier/products/<id>
@supplier_bp.route("/products/<int:product_id>", methods=["DELETE"])
@jwt_required()
def delete_supplier_product(product_id):
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT product_id FROM products WHERE product_id = %s AND created_by = %s", (product_id, user_id))
    if not cursor.fetchone():
        return jsonify({"error": "Product not found or access denied"}), 404

    cursor.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
    db.commit()
    cursor.close()

    return jsonify({"message": "Product deleted successfully"}), 200

# GET /api/supplier/purchase-orders — list all POs for this supplier
@supplier_bp.route("/purchase-orders", methods=["GET"])
@jwt_required()
def get_purchase_orders():
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    status = request.args.get("status")  # optional filter e.g. ?status=pending
    page   = max(1, int(request.args.get("page", 1)))
    limit  = min(100, int(request.args.get("limit", 20)))
    offset = (page - 1) * limit

    filters = ["po.supplier_id = %s"]
    params  = [user_id]

    if status:
        filters.append("po.status = %s")
        params.append(status)

    where = "WHERE " + " AND ".join(filters)

    cursor.execute(f"""
        SELECT po.po_id, po.quantity_requested, po.status,
               po.auto_generated, po.created_at, po.updated_at,
               p.product_id, p.product_name, p.unit, p.product_photo,
               u.username AS requested_by_name
        FROM purchase_orders po
        JOIN products p ON p.product_id = po.product_id
        LEFT JOIN users u ON u.user_id = po.requested_by
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
        "total":  total,
        "page":   page,
        "limit":  limit,
        "pages":  (total + limit - 1) // limit,
    }), 200


# GET /api/supplier/purchase-orders/<id> — view single PO
@supplier_bp.route("/purchase-orders/<int:po_id>", methods=["GET"])
@jwt_required()
def get_purchase_order(po_id):
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT po.*, p.product_name, p.unit, p.product_photo,
               u.username AS requested_by_name
        FROM purchase_orders po
        JOIN products p ON p.product_id = po.product_id
        LEFT JOIN users u ON u.user_id = po.requested_by
        WHERE po.po_id = %s AND po.supplier_id = %s
    """, (po_id, user_id))
    order = cursor.fetchone()
    cursor.close()

    if not order:
        return jsonify({"error": "Purchase order not found or access denied"}), 404

    return jsonify({"purchase_order": order}), 200


# PATCH /api/supplier/purchase-orders/<id>/respond — accept or reject
@supplier_bp.route("/purchase-orders/<int:po_id>/respond", methods=["PATCH"])
@jwt_required()
def respond_to_purchase_order(po_id):
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM purchase_orders
        WHERE po_id = %s AND supplier_id = %s
    """, (po_id, user_id))
    order = cursor.fetchone()

    if not order:
        return jsonify({"error": "Purchase order not found or access denied"}), 404

    if order["status"] != "pending":
        return jsonify({"error": f"Cannot respond to a PO with status '{order['status']}'"}), 400

    data   = request.get_json() or {}
    action = (data.get("action") or "").strip().lower()

    if action not in ("accept", "reject"):
        return jsonify({"error": "action must be 'accept' or 'reject'"}), 400

    new_status = "accepted" if action == "accept" else "rejected"

    cursor.execute("""
        UPDATE purchase_orders SET status = %s WHERE po_id = %s
    """, (new_status, po_id))
    db.commit()
    cursor.close()

    return jsonify({
        "message": f"Purchase order {new_status} successfully",
        "po_id":   po_id,
        "status":  new_status,
    }), 200


# PATCH /api/supplier/purchase-orders/<id>/dispatch — confirm dispatch
@supplier_bp.route("/purchase-orders/<int:po_id>/dispatch", methods=["PATCH"])
@jwt_required()
def confirm_dispatch(po_id):
    err = require_approved_supplier()
    if err:
        return err

    user_id = get_jwt_identity()
    db = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT * FROM purchase_orders
        WHERE po_id = %s AND supplier_id = %s
    """, (po_id, user_id))
    order = cursor.fetchone()

    if not order:
        return jsonify({"error": "Purchase order not found or access denied"}), 404

    if order["status"] != "accepted":
        return jsonify({"error": "Only accepted purchase orders can be dispatched"}), 400

    data          = request.get_json() or {}
    delivery_date = data.get("delivery_date")  # expected format: YYYY-MM-DD

    if not delivery_date:
        return jsonify({"error": "delivery_date is required"}), 400

    # Update PO status to fulfilled
    cursor.execute("""
        UPDATE purchase_orders SET status = 'fulfilled' WHERE po_id = %s
    """, (po_id,))

    # Create a delivery record
    cursor.execute("""
        INSERT INTO deliveries (po_id, quantity_delivered, status, delivery_date)
        VALUES (%s, %s, 'scheduled', %s)
    """, (po_id, order["quantity_requested"], delivery_date))

    db.commit()
    delivery_id = cursor.lastrowid
    cursor.close()

    return jsonify({
        "message":     "Dispatch confirmed, delivery scheduled",
        "po_id":       po_id,
        "delivery_id": delivery_id,
        "status":      "fulfilled",
    }), 200