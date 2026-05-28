import mysql.connector
from flask import current_app, g


def get_db():
    """Get a database connection, reusing one per request."""
    if "db" not in g:
        g.db = mysql.connector.connect(
            host=current_app.config["MYSQL_HOST"],
            port=current_app.config["MYSQL_PORT"],
            user=current_app.config["MYSQL_USER"],
            password=current_app.config["MYSQL_PASSWORD"],
            database=current_app.config["MYSQL_DB"],
            autocommit=False,
        )
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create all required tables if they don't exist."""
    conn = mysql.connector.connect(
        host=current_app.config["MYSQL_HOST"],
        port=current_app.config["MYSQL_PORT"],
        user=current_app.config["MYSQL_USER"],
        password=current_app.config["MYSQL_PASSWORD"],
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

    conn.commit()
    cursor.close()
    conn.close()
    print("Sokoni database and tables initialized.")