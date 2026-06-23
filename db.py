import os
import mysql.connector
from flask import current_app, g


def _ssl_args(host: str) -> dict:
    """Return SSL kwargs for mysql.connector based on environment."""
    if host in ("localhost", "127.0.0.1"):
        return {}
    ca = os.getenv("MYSQL_SSL_CA", "")
    if ca:
        return {"ssl_ca": ca, "ssl_verify_cert": True}
    # Remote host without CA file — connect without SSL
    return {}


def get_db():
    """Get a database connection, reusing one per request."""
    if "db" not in g:
        host = current_app.config["MYSQL_HOST"]
        g.db = mysql.connector.connect(
            host=host,
            port=current_app.config["MYSQL_PORT"],
            user=current_app.config["MYSQL_USER"],
            password=current_app.config["MYSQL_PASSWORD"],
            database=current_app.config["MYSQL_DB"],
            autocommit=False,
            **_ssl_args(host),
        )
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create all required tables if they don't exist."""
    host = current_app.config["MYSQL_HOST"]
    conn = mysql.connector.connect(
        host=host,
        port=current_app.config["MYSQL_PORT"],
        user=current_app.config["MYSQL_USER"],
        password=current_app.config["MYSQL_PASSWORD"],
        **_ssl_args(host),
    )
    cursor = conn.cursor()

    # Create database
    cursor.execute(f"CREATE DATABASE IF NOT EXISTS {current_app.config['MYSQL_DB']}")
    cursor.execute(f"USE {current_app.config['MYSQL_DB']}")

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INT AUTO_INCREMENT PRIMARY KEY,
            username      VARCHAR(100) NOT NULL UNIQUE,
            email         VARCHAR(150) NOT NULL UNIQUE,
            phone         VARCHAR(20)  NOT NULL,
            password      VARCHAR(255) NOT NULL,
            is_active     TINYINT(1)   NOT NULL DEFAULT 0,
            activation_code VARCHAR(6),
            activation_expires DATETIME,
            role          ENUM('customer','admin') NOT NULL DEFAULT 'customer',
            created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Products table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product_id    INT AUTO_INCREMENT PRIMARY KEY,
            product_name  VARCHAR(200) NOT NULL,
            product_cost  DECIMAL(10,2) NOT NULL,
            product_desc  TEXT,
            product_photo VARCHAR(255),
            stock         INT NOT NULL DEFAULT 0,
            created_by    INT,
            created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(user_id) ON DELETE SET NULL
        )
    """)

    # Cart table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            cart_id       INT AUTO_INCREMENT PRIMARY KEY,
            user_id       INT NOT NULL,
            product_id    INT NOT NULL,
            quantity      INT NOT NULL DEFAULT 1,
            added_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id)    REFERENCES users(user_id)    ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE,
            UNIQUE KEY unique_cart_item (user_id, product_id)
        )
    """)

    # Orders table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id      INT AUTO_INCREMENT PRIMARY KEY,
            user_id       INT NOT NULL,
            total_amount  DECIMAL(10,2) NOT NULL,
            status        ENUM('pending','paid','shipped','delivered','cancelled') NOT NULL DEFAULT 'pending',
            mpesa_checkout_id VARCHAR(100),
            mpesa_receipt   VARCHAR(100),
            created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)

    # Order items table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            item_id       INT AUTO_INCREMENT PRIMARY KEY,
            order_id      INT NOT NULL,
            product_id    INT NOT NULL,
            quantity      INT NOT NULL,
            unit_price    DECIMAL(10,2) NOT NULL,
            FOREIGN KEY (order_id)   REFERENCES orders(order_id)   ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE CASCADE
        )
    """)

    # Promo codes table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            promo_id         INT AUTO_INCREMENT PRIMARY KEY,
            code             VARCHAR(50)  NOT NULL UNIQUE,
            type             ENUM('percent','flat') NOT NULL DEFAULT 'percent',
            value            DECIMAL(10,2) NOT NULL,
            min_order_amount DECIMAL(10,2) DEFAULT 0,
            max_uses         INT DEFAULT NULL,
            used_count       INT DEFAULT 0,
            expires_at       DATETIME DEFAULT NULL,
            is_active        TINYINT(1) DEFAULT 1,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migrate orders table — add promo / discount columns if missing
    for col, definition in [
        ("promo_code",      "VARCHAR(50) DEFAULT NULL"),
        ("discount_amount", "DECIMAL(10,2) DEFAULT 0"),
    ]:
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'orders'
              AND COLUMN_NAME  = %s
        """, (col,))
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {definition}")

    conn.commit()
    cursor.close()
    conn.close()
    print("Sokoni database and tables initialized.")