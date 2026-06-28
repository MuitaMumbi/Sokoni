import smtplib
import random
import string
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import resend
from flask import current_app
import os


MAIL_SERVER    = "smtp.gmail.com"
MAIL_PORT     = 587
MAIL_USERNAME = os.getenv("EMAIL_USER")    
MAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

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

        resend.api_key = current_app.config["RESEND_API_KEY"]

        response = resend.Emails.send({
            "from": "Sokoni <onboarding@resend.dev>",
            "to": to_email,
            "subject": "Sokoni – Verify Your Account",
            "html": html_body
        })

        if not response.get("id"):
            current_app.logger.error(f"[EMAIL] Resend returned no ID for {to_email}: {response}")
            return False

        current_app.logger.info(f"[EMAIL] Activation email sent to {to_email}, id: {response['id']}")
        return True
    except Exception as e:
        import traceback
        current_app.logger.error(f"[EMAIL] Failed to send to {to_email}: {type(e).__name__} - {e}")
        current_app.logger.error(traceback.format_exc())
        return False
    
def send_reset_email(to_email: str, username: str, token: str) -> bool:
    """Send a password reset email with the reset link."""

    reset_url = f"http://localhost:5173/reset-password?token={token}&email={to_email}"

    try:
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;">
          <div style="max-width:500px;margin:auto;background:#fff;border-radius:10px;padding:30px;">
            <h2 style="color:#0A2E6E;">Sokoni Password Reset 🔑</h2>
            <p>Hi <strong>{username}</strong>,</p>
            <p>You requested to reset your password. Click the button below:</p>
            <div style="text-align:center;margin:30px 0;">
              <a href="{reset_url}"
                 style="background:#F5C800;color:#0A2E6E;padding:14px 28px;border-radius:8px;
                        font-weight:bold;font-size:15px;text-decoration:none;display:inline-block;">
                Reset My Password
              </a>
            </div>
            <p style="color:#757575;font-size:13px;">
              This link expires in <strong>30 minutes</strong>.<br>
              If you did not request a password reset, please ignore this email.
            </p>
            <p style="color:#9e9e9e;font-size:12px;">
              Or copy this link into your browser:<br>
              <a href="{reset_url}" style="color:#2B6BE0;">{reset_url}</a>
            </p>
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
            <p style="color:#9e9e9e;font-size:12px;text-align:center;">
              &copy; 2025 Sokoni. All rights reserved.
            </p>
          </div>
        </body>
        </html>
        """

        resend.api_key = current_app.config["RESEND_API_KEY"]

        response = resend.Emails.send({
            "from": "Sokoni <onboarding@resend.dev>",
            "to": to_email,
            "subject": "Sokoni – Password Reset",
            "html": html_body
        })

        if not response.get("id"):
            current_app.logger.error(f"[EMAIL] Resend returned no ID for {to_email}: {response}")
            return False

        current_app.logger.info(f"[EMAIL] Reset email sent to {to_email}, id: {response['id']}")
        return True

    except Exception as e:
        import traceback
        current_app.logger.error(f"[EMAIL] Failed to send reset email to {to_email}: {type(e).__name__} - {e}")
        current_app.logger.error(traceback.format_exc())
        return False