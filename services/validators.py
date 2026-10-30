"""services/validators.py - server-side input validation (never trust the browser)."""
import re

STUDENT_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{1,29}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,30}$")


class ValidationError(ValueError):
    """Raised with a message that is safe to show to the administrator."""


def clean_text(value, field: str, min_len: int = 1, max_len: int = 100) -> str:
    value = " ".join((value or "").split())          # trim + collapse whitespace
    if len(value) < min_len:
        raise ValidationError(f"{field} is required.")
    if len(value) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters.")
    if any(ord(ch) < 32 for ch in value):
        raise ValidationError(f"{field} contains invalid characters.")
    return value


def validate_student_form(form) -> dict:
    code = (form.get("student_code") or "").strip()
    if not STUDENT_CODE_RE.match(code):
        raise ValidationError("ID must be 2-30 characters: letters, digits, '-' or '_' (no spaces).")
    email = (form.get("email") or "").strip()
    if email and (len(email) > 120 or not EMAIL_RE.match(email)):
        raise ValidationError("Email address is not valid.")
    if form.get("consent") not in ("on", "yes", "true", "1"):
        raise ValidationError("Informed consent is required before any face data can be collected.")
    return {
        "student_code": code,
        "full_name": clean_text(form.get("full_name"), "Full name", 2, 100),
        "department": clean_text(form.get("department"), "Department", 1, 60),
        "class_name": clean_text(form.get("class_name"), "Class / semester / designation", 1, 60),
        "email": email,
    }


def validate_password(password: str) -> None:
    if len(password or "") < 8:
        raise ValidationError("Password must be at least 8 characters long.")
    if not (re.search(r"[a-z]", password) and re.search(r"[A-Z]", password) and re.search(r"\d", password)):
        raise ValidationError("Password needs an uppercase letter, a lowercase letter and a digit.")
    if len(password) > 128:
        raise ValidationError("Password is too long (max 128 characters).")


def validate_session_name(name: str) -> str:
    return clean_text(name, "Session name", 2, 80)
