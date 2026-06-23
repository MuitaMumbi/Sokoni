import re


# Email
EMAIL_RE = re.compile(r"^[\w\.\+\-]+@[\w\-]+\.[a-z]{2,}$", re.IGNORECASE)

def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


# Phone (Kenyan format)
PHONE_RE = re.compile(r"^(?:\+?254|0)[17]\d{8}$")

def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(phone.strip()))


#  Username 
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,30}$")

def is_valid_username(username: str) -> bool:
    """Only letters, numbers, underscores. 3-30 chars."""
    return bool(USERNAME_RE.match(username.strip()))


# Password strength 
def is_strong_password(password: str) -> tuple[bool, str]:
    """
    Returns (True, "") if strong, or (False, reason) if weak.
    Rules: 8+ chars, 1 uppercase, 1 lowercase, 1 digit, 1 special char.
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character"
    return True, ""


#  Sanitize string input 
def sanitize_string(value: str, max_length: int = 255) -> str:
    """Strip whitespace and truncate to max_length."""
    return str(value).strip()[:max_length]


#  Positive number
def is_positive_number(value) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


#  Positive integer 
def is_positive_integer(value) -> bool:
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False