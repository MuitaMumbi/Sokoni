import os
import uuid
from werkzeug.security import generate_password_hash
from flask import Blueprint, request, jsonify
from db import get_db

seed_bp = Blueprint("seed", __name__)

SEED_TOKEN = os.getenv("SEED_TOKEN", "")


@seed_bp.route("/", methods=["POST"])
def run_seed():
    if not SEED_TOKEN or request.headers.get("X-Seed-Token") != SEED_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    db     = get_db()
    cursor = db.cursor(dictionary=True)

    # ── Admin user ──────────────────────────────────────────────
    cursor.execute("SELECT user_id FROM users WHERE email='admin@sokoni.com'")
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO users (username, email, phone, password, role, is_active, is_approved)
            VALUES (%s, %s, %s, %s, 'admin', 1, 1)
        """, ("admin", "admin@sokoni.com", "0700000000",
              generate_password_hash("Admin1234!")))

    # ── Categories ──────────────────────────────────────────────
    categories = [
        ("Phones",                 "phones"),
        ("Electronics",            "electronics"),
        ("Computers & Accessories","computers-accessories"),
        ("Fashion & Clothing",     "fashion-clothing"),
        ("Home & Kitchen",         "home-kitchen"),
        ("Sports & Fitness",       "sports-fitness"),
        ("Food & Agriculture",     "food-agriculture"),
    ]
    for name, slug in categories:
        cursor.execute("SELECT category_id FROM categories WHERE slug=%s", (slug,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO categories (name, slug) VALUES (%s, %s)", (name, slug)
            )
    db.commit()

    cursor.execute("SELECT category_id, slug FROM categories")
    cat_map = {r["slug"]: r["category_id"] for r in cursor.fetchall()}

    # ── Products ────────────────────────────────────────────────
    products = [
        ("Samsung Galaxy A55",      45000, "6.6-inch display, 50MP camera, 5000mAh battery",                          12, "https://images.unsplash.com/photo-1610945415295-d9bbf067e59c?w=600&q=80", cat_map.get("phones")),
        ("Apple AirPods Pro",       28000, "Active noise cancellation, spatial audio, MagSafe charging case",          8,  "https://images.unsplash.com/photo-1572569511254-d8f925fe2cbb?w=600&q=80", cat_map.get("electronics")),
        ("Nike Air Max 270",        12500, "Men's running shoes, lightweight cushioning, sizes 40-46",                 15, "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&q=80",  cat_map.get("fashion-clothing")),
        ("Leather Handbag",         3800,  "Genuine leather, multiple compartments, adjustable strap",                 20, "https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=600&q=80",  cat_map.get("fashion-clothing")),
        ("Instant Pot 6QT",         9500,  "7-in-1 multi-use pressure cooker, slow cooker, rice cooker",              10, "https://images.unsplash.com/photo-1556909211-36987daf7b4d?w=600&q=80",  cat_map.get("home-kitchen")),
        ("HP Laptop 15s",           62000, "Intel Core i5, 8GB RAM, 512GB SSD, 15.6-inch FHD display",                6,  "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=600&q=80", cat_map.get("computers-accessories")),
        ("Wireless Keyboard & Mouse",4200, "2.4GHz wireless, ergonomic design, long battery life",                    25, "https://images.unsplash.com/photo-1595044426077-d36d9236d54a?w=600&q=80", cat_map.get("computers-accessories")),
        ("Cotton Bedsheet Set",     2800,  "King size, 100% cotton, includes 2 pillowcases",                          30, "https://images.unsplash.com/photo-1631049307264-da0ec9d70304?w=600&q=80", cat_map.get("home-kitchen")),
        ("Blender Pro 2L",          5500,  "1200W motor, stainless steel blades, 5-speed settings",                   18, "https://images.unsplash.com/photo-1570222094114-d054a817e56b?w=600&q=80", cat_map.get("home-kitchen")),
        ("Men's Polo Shirt",        1500,  "100% cotton, available in navy, white, black. Sizes S-XXL",               40, "https://images.unsplash.com/photo-1586363104862-3a5e2ab60d99?w=600&q=80",  cat_map.get("fashion-clothing")),
        ("Yoga Mat",                2200,  "6mm thick non-slip surface, includes carrying strap",                      22, "https://images.unsplash.com/photo-1601925228717-1d2b4a6aa272?w=600&q=80",  cat_map.get("sports-fitness")),
        ("Smart Watch X200",        8900,  "Heart rate monitor, GPS, waterproof, 7-day battery life",                 14, "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600&q=80",  cat_map.get("electronics")),
        ("Maize",                   1200,  "Grade 1 white maize, 90kg bag, sourced from Rift Valley",                 50, "https://images.unsplash.com/photo-1615485290161-7eb49a34eba5?w=600&q=80",  cat_map.get("food-agriculture")),
        ("iPhone 17",               95000, "6.1-inch Super Retina XDR, A19 chip, 48MP camera system",                5,  "https://images.unsplash.com/photo-1726839662758-e3b5da59b0fb?w=600&q=80",  cat_map.get("phones")),
    ]

    inserted = 0
    for name, cost, desc, stock, photo, cat_id in products:
        cursor.execute("SELECT product_id FROM products WHERE product_name=%s", (name,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO products (product_name, product_cost, product_desc, stock, product_photo, category_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (name, cost, desc, stock, photo, cat_id))
            inserted += 1

    db.commit()
    cursor.close()

    return jsonify({
        "message": "Seed complete",
        "products_inserted": inserted,
        "admin": "admin@sokoni.com / Admin1234!",
    }), 200
