from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from config import Config
from db import init_db
from routes.auth import auth_bp
from routes.products import products_bp
from routes.cart import cart_bp
from routes.orders import orders_bp
from routes.mpesa import mpesa_bp

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

# Initialize DB tables on startup
with app.app_context():
    init_db()

@app.route("/")
def index():
    return {"message": "Welcome to Sokoni API 🛒", "version": "1.0.0"}, 200

if __name__ == "__main__":
    app.run(debug=True, port=5000)