from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from db import get_db

categories_bp = Blueprint("categories", __name__)


def require_admin():
    claims = get_jwt()
    if claims.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
    return None


#  GET /api/categories/
@categories_bp.route("/", methods=["GET"])
def get_categories():
    db     = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT c.category_id, c.name, c.slug, c.parent_id,
               COUNT(p.product_id) AS product_count
        FROM categories c
        LEFT JOIN products p ON p.category_id = c.category_id
        GROUP BY c.category_id
        ORDER BY c.parent_id IS NOT NULL, c.name
    """)
    categories = cursor.fetchall()
    cursor.close()
    return jsonify({"categories": categories}), 200


#  POST /api/categories/  (admin)
@categories_bp.route("/", methods=["POST"])
@jwt_required()
def create_category():
    err = require_admin()
    if err:
        return err

    data = request.get_json() or {}
    name = data.get("name", "").strip()
    slug = data.get("slug", "").strip().lower().replace(" ", "-")
    parent_id = data.get("parent_id")

    if not name or not slug:
        return jsonify({"error": "name and slug are required"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT category_id FROM categories WHERE slug=%s", (slug,))
    if cursor.fetchone():
        return jsonify({"error": "Slug already exists"}), 409

    cursor.execute(
        "INSERT INTO categories (name, slug, parent_id) VALUES (%s, %s, %s)",
        (name, slug, parent_id or None)
    )
    db.commit()
    category_id = cursor.lastrowid
    cursor.close()

    return jsonify({"message": "Category created", "category_id": category_id}), 201


#  GET /api/categories/<id>
@categories_bp.route("/<int:category_id>", methods=["GET"])
def get_category(category_id):
    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM categories WHERE category_id=%s", (category_id,))
    category = cursor.fetchone()
    if not category:
        return jsonify({"error": "Category not found"}), 404

    cursor.execute("""
        SELECT category_id, name, slug FROM categories WHERE parent_id=%s
    """, (category_id,))
    category["subcategories"] = cursor.fetchall()
    cursor.close()

    return jsonify({"category": category}), 200


#  DELETE /api/categories/<id>  (admin)
@categories_bp.route("/<int:category_id>", methods=["DELETE"])
@jwt_required()
def delete_category(category_id):
    err = require_admin()
    if err:
        return err

    db     = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM categories WHERE category_id=%s", (category_id,))
    db.commit()
    cursor.close()
    return jsonify({"message": "Category deleted"}), 200
