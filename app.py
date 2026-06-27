import logging
import os
from logging.handlers import RotatingFileHandler
from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from flask_talisman import Talisman
from config import Config
from db import init_db
from flask_cors import CORS

#Logging Setup
os.makedirs("logs", exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sokoni")

# Rotating file log — max 5MB per file, keep 5 backups
file_handler = RotatingFileHandler("logs/sokoni.log", maxBytes=5_000_000, backupCount=5)
file_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] %(levelname)s %(module)s: %(message)s"
))
logger.addHandler(file_handler)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    # HTTPS enforcement (Talisman) 
    # Forces HTTPS and sets strict security headers on every response
    # Disable in local dev by setting FORCE_HTTPS=False in .env
    Talisman(
        app,
        force_https=app.config.get("FORCE_HTTPS", False),   # True in production
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,          # 1 year
        content_security_policy=False,                       # Let mobile app handle CSP
        x_content_type_options=True,
        frame_options="DENY",
        referrer_policy="strict-origin-when-cross-origin",
    )

    # CORS
    # Only allow requests from your mobile app domain
    CORS(app, resources={
        r"/api/*": {
            "origins": app.config.get("ALLOWED_ORIGINS", "*"),
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type"],
        }
    })

    # JWT
    jwt = JWTManager(app)

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Token has expired. Please sign in again."}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({"error": "Invalid token. Please sign in again."}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({"error": "Authorization token is missing."}), 401

    # Rate Limiting
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per hour", "50 per minute"],
        storage_uri="memory://",
    )

    # Security Headers on every response 
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"]  = "nosniff"
        response.headers["X-Frame-Options"]         = "DENY"
        response.headers["Cache-Control"]           = "no-store"
        response.headers["Pragma"]                  = "no-cache"
        # Remove Flask version fingerprint
        response.headers.pop("X-Powered-By", None)
        return response

    # Request Logging 
    @app.before_request
    def log_request():
        # Never log Authorization headers or passwords
        logger.info(f"→ {request.method} {request.path} | IP: {request.remote_addr}")

    @app.after_request
    def log_response(response):
        logger.info(f"← {response.status_code} {request.method} {request.path}")
        return response

    # Global Error Handlers 
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request"}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"error": "Unauthorized"}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"error": "Forbidden"}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(429)
    def rate_limit_exceeded(e):
        logger.warning(f"Rate limit exceeded | IP: {request.remote_addr} | {request.path}")
        return jsonify({"error": "Too many requests. Please slow down."}), 429

    @app.errorhandler(500)
    def internal_error(e):
        # Log full error internally, return generic message to client
        logger.error(f"500 Internal Error: {e} | Path: {request.path}", exc_info=True)
        return jsonify({"error": "An internal server error occurred."}), 500

    # Register Blueprints with rate limits 
    from routes.auth     import auth_bp
    from routes.products import products_bp
    from routes.cart     import cart_bp
    from routes.orders   import orders_bp
    from routes.mpesa    import mpesa_bp

    # Stricter limits on auth endpoints to prevent brute force
    limiter.limit("10 per minute")(auth_bp)

    app.register_blueprint(auth_bp,     url_prefix="/api/auth")
    app.register_blueprint(products_bp, url_prefix="/api/products")
    app.register_blueprint(cart_bp,     url_prefix="/api/cart")
    app.register_blueprint(orders_bp,   url_prefix="/api/orders")
    app.register_blueprint(mpesa_bp,    url_prefix="/api/mpesa")

    # Initialize DB 
    with app.app_context():
        init_db()

    # Health check endpoint 
    @app.route("/")
    def index():
        return jsonify({"message": "Welcome to Sokoni API 🛒", "version": "1.0.0"}), 200

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    logger.info("✅ Sokoni API started successfully")
    return app


app = create_app()

if __name__ == "__main__":
    # Render assigns a dynamic port via environment variables. Default to 5000 for localhost.
    port = int(os.environ.get("PORT", 5000))
    
    # Never run with debug=True in production
    debug_mode = app.config.get("DEBUG", False)
    
    # host="0.0.0.0" allows Render's network to route public traffic to your app
    app.run(host="0.0.0.0", port=port, debug=debug_mode)