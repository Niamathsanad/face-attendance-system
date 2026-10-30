"""routes/auth_routes.py - login, logout, profile, password change, system settings."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from flask import current_app

from config import Config
from database.db import get_db
from models.face_recognition_model import get_engine
from services import security
from services.audit_service import log_action
from services.security import current_admin, login_required
from services.settings_service import SETTING_SPECS, get_all, set_setting
from services.time_utils import now_utc_iso, tz_name
from services.validators import (EMAIL_RE, ValidationError, clean_text, validate_password)

bp = Blueprint("auth", __name__)
_DUMMY_HASH = None


def _dummy_hash() -> str:
    """Used so that unknown usernames take as long as known ones (no timing leak)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = generate_password_hash("not-a-real-password", method=Config.PASSWORD_HASH_METHOD)
    return _DUMMY_HASH


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_id"):
        return redirect(url_for("dashboard.dashboard"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()[:60]
        password = request.form.get("password") or ""
        db = get_db()
        wait = security.is_locked(username)
        if wait:
            flash(f"Too many failed attempts. Try again in {wait} seconds.", "danger")
            return render_template("login.html"), 429
        row = db.execute("SELECT * FROM administrators WHERE username = ?", (username,)).fetchone()
        ok = check_password_hash(row["password_hash"] if row else _dummy_hash(), password) and row is not None
        if not ok:
            security.register_failure(username)
            log_action(db, None, username, "login_failed", "admin", username, {}, security.client_ip())
            flash("Invalid username or password.", "danger")
            return render_template("login.html"), 401
        security.register_success(username)
        session.clear()                                # new session id after login (prevents fixation)
        session.permanent = True
        session["admin_id"] = row["id"]
        session["admin_username"] = row["username"]
        session["must_change"] = bool(row["must_change_password"])
        db.execute("UPDATE administrators SET last_login_at = ? WHERE id = ?", (now_utc_iso(), row["id"]))
        db.commit()
        log_action(db, row["id"], row["username"], "login", "admin", row["username"], {}, security.client_ip())
        if session["must_change"]:
            flash("Please set a new password before continuing.", "warning")
            return redirect(url_for("auth.profile"))
        nxt = request.args.get("next")
        return redirect(nxt if security.is_safe_next(nxt) else url_for("dashboard.dashboard"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    admin = current_admin()
    log_action(get_db(), admin["id"], admin["username"], "logout", "admin", admin["username"], {}, security.client_ip())
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/profile")
@login_required
def profile():
    db = get_db()
    me = db.execute("SELECT id, username, full_name, email, created_at, last_login_at FROM administrators WHERE id = ?",
                    (session["admin_id"],)).fetchone()
    return render_template("profile.html", me=me, settings=get_all(db), specs=SETTING_SPECS,
                           model_name=get_engine().model_name, tz=tz_name(),
                           forced=bool(session.get("must_change")))


@bp.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    db = get_db()
    try:
        full_name = clean_text(request.form.get("full_name"), "Full name", 2, 100)
        email = (request.form.get("email") or "").strip()
        if email and not EMAIL_RE.match(email):
            raise ValidationError("Email address is not valid.")
        db.execute("UPDATE administrators SET full_name = ?, email = ? WHERE id = ?", (full_name, email, session["admin_id"]))
        db.commit()
        flash("Profile updated.", "success")
    except ValidationError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("auth.profile"))


@bp.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    db = get_db()
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""
    row = db.execute("SELECT * FROM administrators WHERE id = ?", (session["admin_id"],)).fetchone()
    try:
        if not check_password_hash(row["password_hash"], current):
            raise ValidationError("Current password is incorrect.")
        if new != confirm:
            raise ValidationError("New password and confirmation do not match.")
        if check_password_hash(row["password_hash"], new):
            raise ValidationError("Choose a password different from the current one.")
        validate_password(new)
    except ValidationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("auth.profile"))
    db.execute("UPDATE administrators SET password_hash = ?, must_change_password = 0 WHERE id = ?",
               (generate_password_hash(new, method=current_app.config["PASSWORD_HASH_METHOD"]), row["id"]))
    db.commit()
    session["must_change"] = False
    log_action(db, row["id"], row["username"], "password_changed", "admin", row["username"], {}, security.client_ip())
    flash("Password changed successfully.", "success")
    return redirect(url_for("dashboard.dashboard"))


@bp.route("/profile/settings", methods=["POST"])
@login_required
def update_settings():
    db = get_db()
    admin = current_admin()
    try:
        changed = {}
        for key in SETTING_SPECS:
            if request.form.get(key, "") != "":
                set_setting(db, key, request.form[key])
                changed[key] = request.form[key]
        db.commit()
        log_action(db, admin["id"], admin["username"], "settings_changed", "settings", None, changed, security.client_ip())
        flash("Settings saved.", "success")
    except ValidationError as exc:
        db.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("auth.profile"))
