import os
import mysql.connector
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

load_dotenv()

conn = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    port=int(os.getenv("MYSQL_PORT", 3306)),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DB"),
    ssl_ca="ca.pem",
    ssl_verify_cert=True,
)

cursor = conn.cursor()

new_hash = generate_password_hash("Retailer123!", method="pbkdf2:sha256")

cursor.execute(
    "UPDATE users SET password = %s WHERE email = %s",
    (new_hash, "retailer@test.com")
)
conn.commit()
print(f"Done. Rows updated: {cursor.rowcount}")
print(f"Hash starts with: {new_hash[:30]}")
cursor.close()
conn.close()