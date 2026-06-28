from getpass import getpass
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash
from db import get_db
from app import create_app

app = create_app()

with app.app_context():
    db     = get_db()
    cursor = db.cursor()

    username = input("Admin username: ").strip()
    email    = input("Admin email: ").strip().lower()
    phone    = input("Admin phone: ").strip()
    password = getpass("Admin password: ")

    hashed_pw = generate_password_hash(password)
    cursor.execute("""
        INSERT INTO users
            (username, email, password, phone, role, is_active, is_approved)
        VALUES (%s, %s, %s, %s, 'admin', 1, 1)
    """, (username, email, hashed_pw, phone))

    db.commit()
    cursor.close()

    print(f"✅ Admin account created: {email}")
