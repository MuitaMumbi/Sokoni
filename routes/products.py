import os
import uuid
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from werkzeug.utils import secure_filename
from db import get_db

products_bp = Blueprint("products", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def require_admin():
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
    return None


#  POST /api/products/  — Add product (admin)
@products_bp.route("/", methods=["POST"])
@jwt_required()
def add_product():
    err = require_admin()
    if err:
        return err

    user_id = get_jwt_identity()

    # Support multipart/form-data for file upload
    product_name = request.form.get("product_name", "").strip()
    product_cost = request.form.get("product_cost")
    product_desc = request.form.get("product_desc", "")
    stock        = request.form.get("stock", 0)

    if not product_name or product_cost is None:
        return jsonify({"error": "product_name and product_cost are required"}), 400

    try:
        product_cost = float(product_cost)
        stock        = int(stock)
    except ValueError:
        return jsonify({"error": "product_cost must be a number and stock must be an integer"}), 400

    # Handle optional photo upload
    photo_path = None
    if "product_photo" in request.files:
        file = request.files["product_photo"]
        if file and allowed_file(file.filename):
            ext      = secure_filename(file.filename).rsplit(".", 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            upload_dir = current_app.config["UPLOAD_FOLDER"]
            os.makedirs(upload_dir, exist_ok=True)
            file.save(os.path.join(upload_dir, filename))
            photo_path = f"{upload_dir}/{filename}"
        else:
            return jsonify({"error": "Invalid file type. Allowed: png, jpg, jpeg, webp, gif"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        INSERT INTO products (product_name, product_cost, product_desc, product_photo, stock, created_by)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (product_name, product_cost, product_desc, photo_path, stock, user_id))
    db.commit()

    product_id = cursor.lastrowid
    cursor.close()

    return jsonify({
        "message": "Product added successfully",
        "product_id": product_id,
    }), 201



#  GET /api/products/  — List all products
@products_bp.route("/", methods=["GET"])
def get_products():
    db     = get_db()
    cursor = db.cursor(dictionary=True)

    search = request.args.get("search", "")
    page   = max(1, int(request.args.get("page", 1)))
    limit  = min(100, int(request.args.get("limit", 20)))
    offset = (page - 1) * limit

    if search:
        cursor.execute("""
            SELECT product_id, product_name, product_cost, product_desc, product_photo, stock, created_at
            FROM products
            WHERE product_name LIKE %s OR product_desc LIKE %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (f"%{search}%", f"%{search}%", limit, offset))
    else:
        cursor.execute("""
            SELECT product_id, product_name, product_cost, product_desc, product_photo, stock, created_at
            FROM products
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))

    products = cursor.fetchall()

    # Total count
    if search:
        cursor.execute("SELECT COUNT(*) AS total FROM products WHERE product_name LIKE %s OR product_desc LIKE %s",
                       (f"%{search}%", f"%{search}%"))
    else:
        cursor.execute("SELECT COUNT(*) AS total FROM products")

    total = cursor.fetchone()["total"]
    cursor.close()

    return jsonify({
        "products": products,
        "total":    total,
        "page":     page,
        "limit":    limit,
        "pages":    (total + limit - 1) // limit,
    }), 200



#  GET /api/products/<id>  — Single product

@products_bp.route("/<int:product_id>", methods=["GET"])
def get_product(product_id):
    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT p.*, u.username AS added_by
        FROM products p
        LEFT JOIN users u ON p.created_by = u.user_id
        WHERE p.product_id = %s
    """, (product_id,))
    product = cursor.fetchone()
    cursor.close()

    if not product:
        return jsonify({"error": "Product not found"}), 404

    return jsonify({"product": product}), 200



#  PUT /api/products/<id>  — Update product (admin)

@products_bp.route("/<int:product_id>", methods=["PUT"])
@jwt_required()
def update_product(product_id):
    err = require_admin()
    if err:
        return err

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT product_id FROM products WHERE product_id=%s", (product_id,))
    if not cursor.fetchone():
        return jsonify({"error": "Product not found"}), 404

    data         = request.get_json() or {}
    product_name = data.get("product_name")
    product_cost = data.get("product_cost")
    product_desc = data.get("product_desc")
    stock        = data.get("stock")

    updates, values = [], []
    if product_name is not None:
        updates.append("product_name=%s"); values.append(product_name)
    if product_cost is not None:
        updates.append("product_cost=%s"); values.append(float(product_cost))
    if product_desc is not None:
        updates.append("product_desc=%s"); values.append(product_desc)
    if stock is not None:
        updates.append("stock=%s"); values.append(int(stock))

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    values.append(product_id)
    cursor.execute(f"UPDATE products SET {', '.join(updates)} WHERE product_id=%s", values)
    db.commit()
    cursor.close()

    return jsonify({"message": "Product updated successfully"}), 200


#  DELETE /api/products/<id>  — Delete (admin)
@products_bp.route("/<int:product_id>", methods=["DELETE"])
@jwt_required()
def delete_product(product_id):
    err = require_admin()
    if err:
        return err

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT product_id, product_photo FROM products WHERE product_id=%s", (product_id,))
    # os.remove(file_path)
    if not cursor.fetchone():
        return jsonify({"error": "Product not found"}), 404

    cursor.execute("DELETE FROM products WHERE product_id=%s", (product_id,))
    db.commit()
    cursor.close()

    return jsonify({"message": "Product deleted successfully"}), 200