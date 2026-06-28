# scripts/update_admin.py
import getpass
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

    # Change these to whatever you need
    current_email = input("Admin email to update: ").strip()   # identify the admin to update
    new_username  = input("New username: ").strip()
    new_email     = input("New email: ").strip().lower()
    new_password  = getpass("New password: ")

    cursor.execute("""
        UPDATE users
        SET username=%s, email=%s, password=%s
        WHERE email=%s AND role='admin'
    """, (new_username, new_email, generate_password_hash(new_password), current_email))

    db.commit()
    cursor.close()
    print("✅ Admin account updated")