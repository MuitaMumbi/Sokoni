from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from config import Config
from db import init_db
from routes.auth import auth_bp
from routes.products import products_bp
from routes.cart import cart_bp
from routes.orders import orders_bp
from routes.mpesa import mpesa_bp
from routes.categories import categories_bp
from routes.supplier import supplier_bp
from routes.admin import admin_bp
from routes.promos import promos_bp

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

jwt = JWTManager(app)
# Register Blueprints
app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(products_bp, url_prefix="/api/products")
app.register_blueprint(cart_bp, url_prefix="/api/cart")
app.register_blueprint(orders_bp, url_prefix="/api/orders")
app.register_blueprint(mpesa_bp, url_prefix="/api/mpesa")
app.register_blueprint(categories_bp, url_prefix="/api/categories")
app.register_blueprint(supplier_bp, url_prefix="/api/supplier")
app.register_blueprint(admin_bp,    url_prefix="/api/admin")
app.register_blueprint(promos_bp,   url_prefix="/api/promos")

# Initialize DB tables on startup
import logging
with app.app_context():
    try:
        init_db()
    except Exception as e:
        logging.error(f"[DB] init_db failed: {e} — check MYSQL_* env vars")

@app.route("/")
def index():
    return {"message": "Welcome to Sokoni API 🛒", "version": "1.0.0"}, 200

@app.route("/uploads/products/<filename>")
def serve_upload(filename):
    return send_from_directory("uploads/products", filename)

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)