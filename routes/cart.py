from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from db import get_db

cart_bp = Blueprint("cart", __name__)

#  GET /api/cart/  — View cart
@cart_bp.route("/", methods=["GET"])
@jwt_required()
def get_cart():
    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.cart_id, c.quantity, c.added_at,
               p.product_id, p.product_name, p.product_cost, p.product_photo,
               p.unit, p.min_order_qty,
               (c.quantity * p.product_cost) AS subtotal
        FROM cart c
        JOIN products p ON c.product_id = p.product_id
        WHERE c.user_id = %s
        ORDER BY c.added_at DESC
    """, (user_id,))

    items = cursor.fetchall()
    total = sum(float(i["subtotal"]) for i in items)
    cursor.close()

    return jsonify({"cart": items, "total": round(total, 2), "item_count": len(items)}), 200


#  POST /api/cart/  — Add item to cart
@cart_bp.route("/", methods=["POST"])
@jwt_required()
def add_to_cart():
    user_id    = get_jwt_identity()
    data       = request.get_json()
    product_id = data.get("product_id")
    quantity   = int(data.get("quantity", 1))

    if not product_id:
        return jsonify({"error": "product_id is required"}), 400
    if quantity < 1:
        return jsonify({"error": "Quantity must be at least 1"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    # Check product exists and has stock
    cursor.execute("SELECT product_id, stock FROM products WHERE product_id=%s", (product_id,))
    product = cursor.fetchone()
    if not product:
        return jsonify({"error": "Product not found"}), 404
    if product["stock"] < quantity:
        return jsonify({"error": f"Only {product['stock']} item(s) in stock"}), 400

    # Upsert cart item
    cursor.execute("""
        INSERT INTO cart (user_id, product_id, quantity)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
    """, (user_id, product_id, quantity))
    db.commit()
    cursor.close()

    return jsonify({"message": "Item added to cart"}), 200



#  PUT /api/cart/<cart_id>  — Update quantity
@cart_bp.route("/<int:cart_id>", methods=["PUT"])
@jwt_required()
def update_cart_item(cart_id):
    user_id  = get_jwt_identity()
    data     = request.get_json()
    quantity = int(data.get("quantity", 1))

    if quantity < 1:
        return jsonify({"error": "Quantity must be at least 1"}), 400

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT cart_id FROM cart WHERE cart_id=%s AND user_id=%s", (cart_id, user_id))
    if not cursor.fetchone():
        return jsonify({"error": "Cart item not found"}), 404

    cursor.execute("UPDATE cart SET quantity=%s WHERE cart_id=%s", (quantity, cart_id))
    db.commit()
    cursor.close()

    return jsonify({"message": "Cart updated"}), 200


#  DELETE /api/cart/<cart_id>  — Remove item
@cart_bp.route("/<int:cart_id>", methods=["DELETE"])
@jwt_required()
def remove_from_cart(cart_id):
    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor(dictionary=True)

    cursor.execute("SELECT cart_id FROM cart WHERE cart_id=%s AND user_id=%s", (cart_id, user_id))
    if not cursor.fetchone():
        return jsonify({"error": "Cart item not found"}), 404

    cursor.execute("DELETE FROM cart WHERE cart_id=%s", (cart_id,))
    db.commit()
    cursor.close()

    return jsonify({"message": "Item removed from cart"}), 200


#  DELETE /api/cart/  — Clear entire cart
@cart_bp.route("/clear", methods=["DELETE"])
@jwt_required()
def clear_cart():
    user_id = get_jwt_identity()
    db      = get_db()
    cursor  = db.cursor()
    cursor.execute("DELETE FROM cart WHERE user_id=%s", (user_id,))
    db.commit()
    cursor.close()
    return jsonify({"message": "Cart cleared"}), 200