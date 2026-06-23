import smtplib
import random
import string
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import current_app


def generate_activation_code(length=6):
    """Generate a random numeric activation code."""
    return "".join(random.choices(string.digits, k=length))


def send_activation_email(to_email: str, username: str, code: str) -> bool:
    """Send an HTML activation email containing the OTP code."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Sokoni – Verify Your Account"
        msg["From"] = current_app.config["MAIL_SENDER"]
        msg["To"] = to_email

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;">
          <div style="max-width:500px;margin:auto;background:#fff;border-radius:10px;padding:30px;">
            <h2 style="color:#2e7d32;">Welcome to Sokoni 🛒</h2>
            <p>Hi <strong>{username}</strong>,</p>
            <p>Thank you for registering! Use the activation code below to verify your account:</p>
            <div style="text-align:center;margin:30px 0;">
              <span style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#2e7d32;
                           background:#e8f5e9;padding:15px 25px;border-radius:8px;">
                {code}
              </span>
            </div>
            <p style="color:#757575;font-size:13px;">
              This code expires in <strong>30 minutes</strong>.<br>
              If you did not register on Sokoni, please ignore this email.
            </p>
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
            <p style="color:#9e9e9e;font-size:12px;text-align:center;">
              &copy; 2025 Sokoni. All rights reserved.
            </p>
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_body, "html"))

        # with smtplib.SMTP(current_app.config["MAIL_SERVER"],
        #                   current_app.config["MAIL_PORT"], timeout=10) as server:
        #     server.starttls()
        #     server.login(
        #         current_app.config["MAIL_USERNAME"],
        #         current_app.config["MAIL_PASSWORD"],
        #     )
        #     server.sendmail(current_app.config["MAIL_SENDER"], to_email, msg.as_string())

        # return False
    except Exception as e:
        current_app.logger.error(f"[EMAIL] Failed to send to {to_email}: {e}")
        return False
