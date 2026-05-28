"""Run once to migrate existing DB to Phase 1 schema: python migrate.py"""
import mysql.connector
from dotenv import load_dotenv
import os

load_dotenv()

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", 3306)),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_PASSWORD", ""),
    database=os.getenv("MYSQL_DB", "sokoni_db"),
)
cursor = conn.cursor()

migrations = [
    # Users: new role values
    "ALTER TABLE users MODIFY COLUMN role ENUM('retailer','supplier','admin') NOT NULL DEFAULT 'retailer'",
    # Users: rename old 'customer' rows to 'retailer'
    "UPDATE users SET role='retailer' WHERE role='customer'",
    # Users: new columns
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS business_name VARCHAR(200)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS country VARCHAR(50) NOT NULL DEFAULT 'Kenya'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approved TINYINT(1) NOT NULL DEFAULT 1",

    # Categories table
    """CREATE TABLE IF NOT EXISTS categories (
        category_id INT AUTO_INCREMENT PRIMARY KEY,
        name        VARCHAR(100) NOT NULL,
        slug        VARCHAR(100) NOT NULL UNIQUE,
        parent_id   INT,
        created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (parent_id) REFERENCES categories(category_id) ON DELETE SET NULL
    )""",

    # Products: new columns
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id INT",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS min_order_qty INT NOT NULL DEFAULT 1",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS unit VARCHAR(50) NOT NULL DEFAULT 'piece'",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS country VARCHAR(50) NOT NULL DEFAULT 'Kenya'",
    "ALTER TABLE products ADD CONSTRAINT IF NOT EXISTS fk_product_category FOREIGN KEY (category_id) REFERENCES categories(category_id) ON DELETE SET NULL",

    # Orders: new columns
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_address TEXT",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_city VARCHAR(100)",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS country VARCHAR(50) NOT NULL DEFAULT 'Kenya'",

    # Guest orders: make user_id nullable, add buyer contact fields
    "ALTER TABLE orders MODIFY COLUMN user_id INT NULL",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS buyer_name VARCHAR(255) NULL",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS buyer_phone VARCHAR(50) NULL",
    "ALTER TABLE orders ADD COLUMN IF NOT EXISTS buyer_email VARCHAR(255) NULL",
]

for sql in migrations:
    try:
        cursor.execute(sql)
        conn.commit()
        print(f"OK: {sql[:60]}...")
    except mysql.connector.Error as e:
        print(f"SKIP ({e.msg}): {sql[:60]}...")

cursor.close()
conn.close()
print("\nMigration complete.")
