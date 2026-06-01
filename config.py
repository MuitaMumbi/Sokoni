import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "sokoni-super-secret-key-change-in-production")
    DEBUG = os.getenv("DEBUG", "True") == "True"

    # JWT
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "sokoni-jwt-secret-key")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)

    # MySQL Database
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DB = os.getenv("MYSQL_DB", "sokoni_db")
    MYSQL_SSL_CA = os.getenv("MYSQL_SSL_CA", "")

    # Email (for activation codes)
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_USE_TLS = True
    MAIL_SENDER = os.getenv("MAIL_SENDER", "noreply@sokoni.co.ke")

    # File Uploads
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads/products")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB

    # Mpesa Daraja API
    MPESA_CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY", "")
    MPESA_CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET", "")
    MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE", "542542")          # Paybill number
    MPESA_PASSKEY = os.getenv("MPESA_PASSKEY", "")
    MPESA_CALLBACK_URL = os.getenv("MPESA_CALLBACK_URL", "https://yourdomain.com/api/mpesa/callback")
    MPESA_BASE_URL = os.getenv("MPESA_BASE_URL", "https://sandbox.safaricom.co.ke")  # Change to live for production