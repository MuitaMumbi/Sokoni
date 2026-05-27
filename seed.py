"""Run once to seed the database with sample products: python seed.py"""
from app import app
from db import get_db

products = [
    ("Samsung Galaxy A55", 45000, "6.6-inch display, 50MP camera, 5000mAh battery", 12),
    ("Apple AirPods Pro", 28000, "Active noise cancellation, spatial audio, MagSafe charging case", 8),
    ("Nike Air Max 270", 12500, "Men's running shoes, lightweight cushioning, sizes 40-46", 15),
    ("Leather Handbag", 3800, "Genuine leather, multiple compartments, adjustable strap", 20),
    ("Instant Pot 6QT", 9500, "7-in-1 multi-use pressure cooker, slow cooker, rice cooker", 10),
    ("HP Laptop 15s", 62000, "Intel Core i5, 8GB RAM, 512GB SSD, 15.6-inch FHD display", 6),
    ("Wireless Keyboard & Mouse", 4200, "2.4GHz wireless, ergonomic design, long battery life", 25),
    ("Cotton Bedsheet Set", 2800, "King size, 100% cotton, includes 2 pillowcases", 30),
    ("Blender Pro 2L", 5500, "1200W motor, stainless steel blades, 5-speed settings", 18),
    ("Men's Polo Shirt", 1500, "100% cotton, available in navy, white, black. Sizes S-XXL", 40),
    ("Yoga Mat", 2200, "6mm thick non-slip surface, includes carrying strap", 22),
    ("Smart Watch X200", 8900, "Heart rate monitor, GPS, waterproof, 7-day battery life", 14),
]

with app.app_context():
    db = get_db()
    cursor = db.cursor()
    cursor.executemany(
        """INSERT INTO products (product_name, product_cost, product_desc, stock)
           VALUES (%s, %s, %s, %s)""",
        products
    )
    db.commit()
    print(f"Inserted {len(products)} products successfully.")
    cursor.close()
