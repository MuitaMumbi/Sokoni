"""Updates existing products with real image URLs from Unsplash. Run once: python update_images.py"""
from app import app
from db import get_db

# Maps product name fragment → Unsplash image URL
IMAGES = {
    "Samsung":   "https://images.unsplash.com/photo-1610945415295-d9bbf067e59c?w=600&q=80",
    "AirPods":   "https://images.unsplash.com/photo-1588423771073-b8903fead85b?w=600&q=80",
    "Nike":      "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&q=80",
    "Handbag":   "https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=600&q=80",
    "Instant":   "https://images.unsplash.com/photo-1556909211-36987daf7b4d?w=600&q=80",
    "HP":        "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=600&q=80",
    "Keyboard":  "https://images.unsplash.com/photo-1595044426077-d36d9236d54a?w=600&q=80",
    "Bedsheet":  "https://images.unsplash.com/photo-1631049307264-da0ec9d70304?w=600&q=80",
    "Blender":   "https://images.unsplash.com/photo-1570222094114-d054a817e56b?w=600&q=80",
    "Polo":      "https://images.unsplash.com/photo-1586363104862-3a5e2ab60d99?w=600&q=80",
    "Yoga":      "https://images.unsplash.com/photo-1601925228717-1d2b4a6aa272?w=600&q=80",
    "Watch":     "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600&q=80",
}

with app.app_context():
    db     = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT product_id, product_name FROM products")
    products = cursor.fetchall()

    updated = 0
    for p in products:
        name = p["product_name"]
        url  = next((v for k, v in IMAGES.items() if k.lower() in name.lower()), None)
        if url:
            cursor.execute(
                "UPDATE products SET product_photo=%s WHERE product_id=%s",
                (url, p["product_id"])
            )
            updated += 1
            print(f"  {name} -> image set")
        else:
            print(f"  {name} -> no match, skipped")

    db.commit()
    cursor.close()
    print(f"\nDone. {updated}/{len(products)} products updated.")
