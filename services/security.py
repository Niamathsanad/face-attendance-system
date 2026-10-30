"""
services/security.py - login_required, CSRF protection, login throttling, safe redirects.

Protections implemented (OWASP-style):
  * Passwords: salted PBKDF2 hashes (werkzeug) - never stored in plain text.
  * Sessions : signed cookie, HttpOnly, SameSite=Lax, expires after inactivity.
  * CSRF     : every POST needs a secret token (form field or X-CSRF-Token header).
  * Brute force: lock out a username+IP after repeated failed logins.
  * Open redirect: the ?next= parameter only accepts local paths.
  * Headers  : CSP, X-Frame-Options, nosniff, Referrer-Policy, Permissions-Policy.
"""
import hmac
import secrets
import threading
import time
from functools import wraps
from urllib.parse import urlparse

from flask import abort, current_app, jsonify, redirect, request, session, url_for


# ------------------------------------------------------------------ login guard
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Authentication required. Please log in again."}), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def current_admin() -> dict:
    return {"id": session.get("admin_id"), "username": session.get("admin_username")}


def client_ip() -> str:
    return request.remote_addr or "unknown"


def is_safe_next(target: str | None) -> bool:
    """Accept only local paths like /dashboard (blocks //evil.com and http://evil.com)."""
    if not target:
        return False
    parsed = urlparse(target)
    return (not parsed.scheme and not parsed.netloc and target.startswith("/")
            and not target.startswith("//") and "\\" not in target)


# ------------------------------------------------------------------------ CSRF
def get_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def verify_csrf() -> None:
    """Call from before_request. Aborts with 400 when the token is missing/wrong."""
    if not current_app.config.get("CSRF_ENABLED", True):
        return
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf_token", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, description="Security token missing or invalid. Reload the page and try again.")


# ------------------------------------------------------------ login throttling
_attempts: dict[tuple[str, str], dict] = {}
_attempts_lock = threading.Lock()


def _key(username: str) -> tuple[str, str]:
    return (client_ip(), (username or "").lower())


def is_locked(username: str) -> int:
    """Return remaining lock seconds (0 = not locked)."""
    with _attempts_lock:
        rec = _attempts.get(_key(username))
        if rec and rec["locked_until"] > time.time():
            return int(rec["locked_until"] - time.time()) + 1
        return 0


def register_failure(username: str) -> None:
    with _attempts_lock:
        rec = _attempts.setdefault(_key(username), {"count": 0, "locked_until": 0.0})
        if rec["locked_until"] and rec["locked_until"] <= time.time():
            rec["count"], rec["locked_until"] = 0, 0.0
        rec["count"] += 1
        if rec["count"] >= current_app.config["MAX_LOGIN_ATTEMPTS"]:
            rec["locked_until"] = time.time() + current_app.config["LOCKOUT_MINUTES"] * 60


def register_success(username: str) -> None:
    with _attempts_lock:
        _attempts.pop(_key(username), None)


def reset_throttle() -> None:
    with _attempts_lock:
        _attempts.clear()


# ------------------------------------------------------------ security headers
def add_security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"   # do not cache pages with personal data
    return response
