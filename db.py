import os
import mysql.connector
from flask import current_app, g


def _ssl_args(host: str) -> dict:
    """Return SSL kwargs for mysql.connector based on environment."""
    if host in ("localhost", "127.0.0.1"):
        return {}
    # Check env var first, then fall back to ca.pem in project root
    ca = os.getenv("MYSQL_SSL_CA", "")
    if not ca:
        local_ca = os.path.join(os.path.dirname(__file__), "ca.pem")
        if os.path.exists(local_ca):
            ca = local_ca
    if ca:
        return {"ssl_ca": ca, "ssl_verify_cert": True}
    return {"ssl_verify_cert": False}


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
    host   = current_app.config["MYSQL_HOST"]
    db     = current_app.config["MYSQL_DB"]
    is_local = host in ("localhost", "127.0.0.1")

    conn = mysql.connector.connect(
        host=host,
        port=current_app.config["MYSQL_PORT"],
        user=current_app.config["MYSQL_USER"],
        password=current_app.config["MYSQL_PASSWORD"],
        database=None if is_local else db,
        **_ssl_args(host),
    )
    cursor = conn.cursor()

    if is_local:
        # Local dev: create the database if it doesn't exist
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db}")
        cursor.execute(f"USE {db}")
    else:
        # Managed host (Aiven etc.): database already exists, just select it
        cursor.execute(f"USE {db}")

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id            INT AUTO_INCREMENT PRIMARY KEY,
            username           VARCHAR(100) NOT NULL UNIQUE,
            email              VARCHAR(150) NOT NULL UNIQUE,
            phone              VARCHAR(20)  NOT NULL,
            password           VARCHAR(255) NOT NULL,
            is_active          TINYINT(1)   NOT NULL DEFAULT 0,
            is_approved        TINYINT(1)   NOT NULL DEFAULT 0,
            activation_code    VARCHAR(6),
            activation_expires DATETIME,
            role               ENUM('customer','admin','supplier','retailer') NOT NULL DEFAULT 'retailer',
            business_name      VARCHAR(200),
            country            VARCHAR(100) DEFAULT 'Kenya',
            created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reset_token VARCHAR(64) DEFAULT NULL,
            reset_token_expires DATETIME DEFAULT NULL
        )
    """)

    # Categories table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            category_id INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(100) NOT NULL,
            slug        VARCHAR(100) NOT NULL UNIQUE,
            parent_id   INT DEFAULT NULL,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
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
            min_order_qty INT NOT NULL DEFAULT 1,
            unit          VARCHAR(50) DEFAULT 'piece',
            country       VARCHAR(100) DEFAULT 'Kenya',
            category_id   INT,
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
            order_id         INT AUTO_INCREMENT PRIMARY KEY,
            user_id          INT,
            total_amount     DECIMAL(10,2) NOT NULL,
            discount_amount  DECIMAL(10,2) DEFAULT 0,
            promo_code       VARCHAR(50) DEFAULT NULL,
            status           ENUM('pending','paid','shipped','delivered','cancelled') NOT NULL DEFAULT 'pending',
            delivery_address VARCHAR(255),
            delivery_city    VARCHAR(100),
            country          VARCHAR(100) DEFAULT 'Kenya',
            buyer_name       VARCHAR(200),
            buyer_phone      VARCHAR(30),
            buyer_email      VARCHAR(150),
            mpesa_checkout_id VARCHAR(100),
            mpesa_receipt    VARCHAR(100),
            created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
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

    # Token blocklist table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS token_blocklist (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            jti        VARCHAR(64) NOT NULL UNIQUE,  -- JWT unique identifier
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
   

    # Tracks actual warehouse stock per product, separate from products.stock
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            inventory_id        INT AUTO_INCREMENT PRIMARY KEY,
            product_id          INT NOT NULL,
            supplier_id         INT NOT NULL,
            quantity            INT NOT NULL DEFAULT 0,
            low_stock_threshold INT NOT NULL DEFAULT 50,
            updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id)  REFERENCES products(product_id) ON DELETE CASCADE,
            FOREIGN KEY (supplier_id) REFERENCES users(user_id),
            UNIQUE KEY unique_product_supplier (product_id, supplier_id)
        )
    """)


    ## Warehouse -> Supplier: "we need more stock" (auto-generated or manual)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_id              INT AUTO_INCREMENT PRIMARY KEY,
            product_id         INT NOT NULL,
            supplier_id        INT NOT NULL,
            quantity_requested INT NOT NULL,
            status             ENUM('pending','accepted','rejected','fulfilled') DEFAULT 'pending',
            requested_by       INT DEFAULT NULL, 
            auto_generated     BOOLEAN DEFAULT FALSE,
            created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id)   REFERENCES products(product_id),
            FOREIGN KEY (supplier_id)  REFERENCES users(user_id),
            FOREIGN KEY (requested_by) REFERENCES users(user_id)
        )
    """)

    #-- Supplier -> Warehouse: the actual delivery fulfilling a purchase order
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deliveries (
            delivery_id        INT AUTO_INCREMENT PRIMARY KEY,
            po_id              INT NOT NULL,
            quantity_delivered INT NOT NULL,
            status             ENUM('scheduled','in_transit','delivered','cancelled') DEFAULT 'scheduled',
            delivery_date      DATE,
            received_by        INT DEFAULT NULL,
            created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (po_id)         REFERENCES purchase_orders(po_id),
            FOREIGN KEY (received_by)   REFERENCES users(user_id)
        )
    """)

    #-- Money owed to supplier for a delivery
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            invoice_id  INT AUTO_INCREMENT PRIMARY KEY,
            supplier_id INT NOT NULL,
            delivery_id INT NOT NULL,
            amount      DECIMAL(12,2) NOT NULL,
            status      ENUM('unpaid','paid','overdue') DEFAULT 'unpaid',
            due_date    DATE,
            paid_at     TIMESTAMP NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (supplier_id) REFERENCES users(user_id),
            FOREIGN KEY (delivery_id) REFERENCES deliveries(delivery_id)
        )
    """)

     # supplier's profile 
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS supplier_profiles (
            profile_id          INT AUTO_INCREMENT PRIMARY KEY,
            supplier_id         INT NOT NULL UNIQUE,
            company_name        VARCHAR(200),
            business_reg_number VARCHAR(100),
            kra_pin             VARCHAR(50),
            vat_number          VARCHAR(50),
            contact_person      VARCHAR(150),
            phone               VARCHAR(30),
            business_address    TEXT,
            warehouse_address   TEXT,
            bank_name           VARCHAR(100),
            bank_account_number VARCHAR(50),
            bank_account_name   VARCHAR(150),
            mpesa_number        VARCHAR(20),
            mpesa_name          VARCHAR(150),
            logo_url            VARCHAR(255),
            is_complete         TINYINT(1) NOT NULL DEFAULT 0,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (supplier_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_movements (
            movement_id   INT AUTO_INCREMENT PRIMARY KEY,
            inventory_id  INT NOT NULL,
            supplier_id   INT NOT NULL,
            product_id    INT NOT NULL,
            movement_type ENUM('stock_in', 'stock_out', 'adjustment', 'return', 'damage') NOT NULL,
            quantity      INT NOT NULL,
            note          TEXT,
            created_by    INT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (inventory_id) REFERENCES inventory(inventory_id) ON DELETE CASCADE,
            FOREIGN KEY (supplier_id)  REFERENCES users(user_id),
            FOREIGN KEY (product_id)   REFERENCES products(product_id),
            FOREIGN KEY (created_by)   REFERENCES users(user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            notification_id INT AUTO_INCREMENT PRIMARY KEY,
            user_id         INT NOT NULL,
            title           VARCHAR(200) NOT NULL,
            message         TEXT NOT NULL,
            type            ENUM(
                                'product_approved', 'product_rejected',
                                'po_created', 'po_updated',
                                'shipment_received', 'payment_completed',
                                'low_stock', 'announcement'
                            ) NOT NULL,
            is_read         TINYINT(1) NOT NULL DEFAULT 0,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)

    # Column migrations — add any missing columns to existing tables
    migrations = [
        ("users",    "is_approved",        "TINYINT(1) NOT NULL DEFAULT 0"),
        ("users",    "business_name",       "VARCHAR(200) DEFAULT NULL"),
        ("users",    "country",             "VARCHAR(100) DEFAULT 'Kenya'"),
        ("users",    "reset_token",           "VARCHAR(100) DEFAULT NULL"),       
        ("users",    "reset_token_expires",   "DATETIME DEFAULT NULL"),   
        ("products", "min_order_qty",       "INT NOT NULL DEFAULT 1"),
        ("products", "unit",                "VARCHAR(50) DEFAULT 'piece'"),
        ("products", "country",             "VARCHAR(100) DEFAULT 'Kenya'"),
        ("products", "category_id",         "INT DEFAULT NULL"),
        ("orders",   "promo_code",          "VARCHAR(50) DEFAULT NULL"),
        ("orders",   "discount_amount",     "DECIMAL(10,2) DEFAULT 0"),
        ("orders",   "delivery_address",    "VARCHAR(255) DEFAULT NULL"),
        ("orders",   "delivery_city",       "VARCHAR(100) DEFAULT NULL"),
        ("orders",   "country",             "VARCHAR(100) DEFAULT 'Kenya'"),
        ("orders",   "buyer_name",          "VARCHAR(200) DEFAULT NULL"),
        ("orders",   "buyer_phone",         "VARCHAR(30) DEFAULT NULL"),
        ("orders",   "buyer_email",         "VARCHAR(150) DEFAULT NULL"),
        ("products", "is_active", "TINYINT(1) NOT NULL DEFAULT 1"),
    ]
    for table, col, definition in migrations:
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = %s
              AND COLUMN_NAME  = %s
        """, (table, col))
        if cursor.fetchone()[0] == 0:
            cursor.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col}` {definition}")

    # Ensure role ENUM includes all roles
    cursor.execute("""
        ALTER TABLE users MODIFY COLUMN role
        ENUM('customer','admin','supplier','retailer') NOT NULL DEFAULT 'retailer'
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("Sokoni database and tables initialized.")