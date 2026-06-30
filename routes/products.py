import os
import uuid
import cloudinary.uploader
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from werkzeug.utils import secure_filename
from db import get_db

products_bp = Blueprint("products", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_product_photo(file):
    """Uploads to Cloudinary, returns (secure_url, error_message)."""
    if not file or not allowed_file(file.filename):
        return None, "Invalid file type. Allowed: png, jpg, jpeg, webp, gif"
    try:
        result = cloudinary.uploader.upload(
            file,
            folder="sokoni/products",
            public_id=uuid.uuid4().hex,
            resource_type="image",
            overwrite=False,
        )
        return result["secure_url"], None
    except Exception as e:
        return None, f"Image upload failed: {str(e)}"

def require_admin_or_supplier():
    claims = get_jwt()
    if claims.get("role") not in ("admin", "supplier"):
        return jsonify({"error": "Supplier or admin access required"}), 403
    return None


#  POST /api/products/  — Add product (supplier or admin)
@products_bp.route("/", methods=["POST"])
@jwt_required()
def add_product():
    err = require_admin_or_supplier()
    if err:
        return err

    user_id = get_jwt_identity()

    is_multipart = request.content_type and "multipart" in request.content_type
    raw = request.form if is_multipart else (request.get_json() or {})

    product_name  = (raw.get("product_name") or "").strip()
    product_cost  = raw.get("product_cost")
    product_desc  = raw.get("product_desc") or ""
    stock         = raw.get("stock", 0)
    category_id   = raw.get("category_id")
    min_order_qty = raw.get("min_order_qty", 1)
    unit          = (raw.get("unit") or "piece").strip()
    country       = (raw.get("country") or "Kenya").strip()

    if not product_name or product_cost is None:
        return jsonify({"error": "product_name and product_cost are required"}), 400

    try:
        product_cost  = float(product_cost)
        stock         = int(stock)
        min_order_qty = int(min_order_qty)
        category_id   = int(category_id) if category_id else None
    except ValueError:
        return jsonify({"error": "Invalid numeric value in fields"}), 400

    photo_path = None
    if "product_photo" in request.files:
        file = request.files["product_photo"]
        photo_path, upload_err = upload_product_photo(file)
        if upload_err:
            return jsonify({"error": upload_err}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        INSERT INTO products
            (product_name, product_cost, product_desc, product_photo,
             stock, category_id, min_order_qty, unit, country, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (product_name, product_cost, product_desc, photo_path,
          stock, category_id, min_order_qty, unit, country, user_id))
    db.commit()

    product_id = cursor.lastrowid
    cursor.close()

    return jsonify({"message": "Product added successfully", "product_id": product_id}), 201


#  GET /api/products/
@products_bp.route("/", methods=["GET"])
def get_products():
    db     = get_db()
    cursor = db.cursor(dictionary=True)

    search      = request.args.get("search", "")
    category_id = request.args.get("category_id")
    country     = request.args.get("country")
    page        = max(1, int(request.args.get("page", 1)))
    limit       = min(100, int(request.args.get("limit", 20)))
    offset      = (page - 1) * limit

    filters  = []
    params   = []

    if search:
        filters.append("(p.product_name LIKE %s OR p.product_desc LIKE %s)")
        params += [f"%{search}%", f"%{search}%"]
    if category_id:
        filters.append("p.category_id = %s")
        params.append(int(category_id))
    if country:
        filters.append("p.country = %s")
        params.append(country)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    cursor.execute(f"""
        SELECT p.product_id, p.product_name, p.product_cost, p.product_desc,
               p.product_photo, p.stock, p.min_order_qty, p.unit, p.country,
               p.created_at, c.name AS category, u.business_name AS supplier
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.category_id
        LEFT JOIN users u ON p.created_by = u.user_id
        {where}
        ORDER BY p.created_at DESC
        LIMIT %s OFFSET %s
    """, params + [limit, offset])

    products = cursor.fetchall()

    cursor.execute(f"SELECT COUNT(*) AS total FROM products p {where}", params)
    total = cursor.fetchone()["total"]
    cursor.close()

    return jsonify({
        "products": products,
        "total":    total,
        "page":     page,
        "limit":    limit,
        "pages":    (total + limit - 1) // limit,
    }), 200


#  GET /api/products/<id>
@products_bp.route("/<int:product_id>", methods=["GET"])
def get_product(product_id):
    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.*, c.name AS category, u.username AS added_by, u.business_name AS supplier
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.category_id
        LEFT JOIN users u ON p.created_by = u.user_id
        WHERE p.product_id = %s
    """, (product_id,))
    product = cursor.fetchone()
    cursor.close()

    if not product:
        return jsonify({"error": "Product not found"}), 404

    return jsonify({"product": product}), 200


#  PUT /api/products/<id>  — supplier can edit own products; admin can edit any
@products_bp.route("/<int:product_id>", methods=["PUT"])
@jwt_required()
def update_product(product_id):
    err = require_admin_or_supplier()
    if err:
        return err

    claims  = get_jwt()
    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("SELECT product_id, created_by FROM products WHERE product_id=%s", (product_id,))
    product = cursor.fetchone()
    if not product:
        return jsonify({"error": "Product not found"}), 404

    if claims.get("role") == "supplier" and str(product["created_by"]) != str(user_id):
        return jsonify({"error": "You can only edit your own products"}), 403

    is_multipart = request.content_type and "multipart" in request.content_type
    data = request.form if is_multipart else (request.get_json() or {})
    updates, vals = [], []

    for field in ("product_name", "product_desc", "unit", "country"):
        if data.get(field) is not None:
            updates.append(f"{field}=%s"); vals.append(data[field])
    if data.get("product_cost") is not None:
        updates.append("product_cost=%s"); vals.append(float(data["product_cost"]))
    if data.get("stock") is not None:
        updates.append("stock=%s"); vals.append(int(data["stock"]))
    if data.get("min_order_qty") is not None:
        updates.append("min_order_qty=%s"); vals.append(int(data["min_order_qty"]))
    if data.get("category_id") is not None:
        updates.append("category_id=%s"); vals.append(int(data["category_id"]))

    if is_multipart and "product_photo" in request.files:
        file = request.files["product_photo"]
        if file and file.filename:
            photo_url, upload_err = upload_product_photo(file)
            if upload_err:
                return jsonify({"error": upload_err}), 400
            updates.append("product_photo=%s"); vals.append(photo_url)

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    vals.append(product_id)
    cursor.execute(f"UPDATE products SET {', '.join(updates)} WHERE product_id=%s", vals)
    db.commit()
    cursor.close()

    return jsonify({"message": "Product updated successfully"}), 200

#  DELETE /api/products/<id>
@products_bp.route("/<int:product_id>", methods=["DELETE"])
@jwt_required()
def delete_product(product_id):
    err = require_admin_or_supplier()
    if err:
        return err

    claims  = get_jwt()
    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("SELECT product_id, created_by, product_photo FROM products WHERE product_id=%s", (product_id,))
    product = cursor.fetchone()
    if not product:
        return jsonify({"error": "Product not found"}), 404

    if claims.get("role") == "supplier" and str(product["created_by"]) != str(user_id):
        return jsonify({"error": "You can only delete your own products"}), 403

    cursor.execute("DELETE FROM products WHERE product_id=%s", (product_id,))
    db.commit()
    cursor.close()

    return jsonify({"message": "Product deleted successfully"}), 200
