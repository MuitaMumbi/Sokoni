import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY")
    DEBUG = os.getenv("DEBUG", "True") == "True"
    FORCE_HTTPS = os.getenv("FORCE_HTTPS", "False") == "True"   # Set True in production

      # Validate critical secrets are set
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable is not set!")
 
    # JWT 
    JWT_SECRET_KEY            = os.getenv("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES  = timedelta(hours=24)
    JWT_TOKEN_LOCATION        = ["headers"]
    JWT_HEADER_NAME           = "Authorization"
    JWT_HEADER_TYPE           = "Bearer"
 
    if not JWT_SECRET_KEY:
        raise ValueError("JWT_SECRET_KEY environment variable is not set!")

    # MySQL Database
    MYSQL_HOST = os.getenv("MYSQL_HOST")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    MYSQL_USER = os.getenv("MYSQL_USER")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
    MYSQL_DB = os.getenv("MYSQL_DB", "defaultdb")
    MYSQL_SSL_CA = os.getenv("MYSQL_SSL_CA")

    # CORS
    # In production set to your app's domain e.g. "https://sokoni.co.ke"
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")

    # Email (for activation codes)
    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = os.getenv("MAIL_PORT", 587)
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_USE_TLS = True
    MAIL_SENDER = os.getenv("MAIL_SENDER", "mumbimuita01@gmail.com")

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