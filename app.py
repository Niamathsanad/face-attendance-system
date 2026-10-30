"""
app.py - application factory and entry point.

Run:   python app.py          (then open http://127.0.0.1:5000)
"""
import logging
import threading

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from config import Config
from database import db as database
from services import security
from services import time_utils


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_path=str(Config.BASE_DIR / "instance"))
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    app.permanent_session_lifetime = __import__("datetime").timedelta(minutes=app.config["SESSION_LIFETIME_MINUTES"])

    time_utils.configure(app.config["TIMEZONE"])
    database.init_app(app)

    # ---- blueprints ------------------------------------------------------
    from routes.auth_routes import bp as auth_bp
    from routes.student_routes import bp as student_bp
    from routes.attendance_routes import bp as attendance_bp
    from routes.dashboard_routes import bp as dashboard_bp
    from routes.report_routes import bp as report_bp
    for bp in (auth_bp, student_bp, attendance_bp, dashboard_bp, report_bp):
        app.register_blueprint(bp)

    # ---- request hooks ---------------------------------------------------
    @app.before_request
    def _guards():
        security.verify_csrf()
        # force the default admin to change the password before using anything else
        if session.get("admin_id") and session.get("must_change") and request.endpoint not in (
                "auth.profile", "auth.change_password", "auth.logout", "static"):
            return redirect(url_for("auth.profile"))

    app.after_request(security.add_security_headers)

    @app.context_processor
    def _inject():
        open_session = None
        if session.get("admin_id"):
            try:
                from services.attendance_service import get_open_session
                open_session = get_open_session(database.get_db())
            except Exception:
                open_session = None
        return {"csrf_token": security.get_csrf_token, "tz_name": time_utils.tz_name(),
                "admin_username": session.get("admin_username"), "open_session": open_session}

    @app.template_filter("localtime")
    def _localtime(value):
        return time_utils.to_local_str(value)

    # ---- friendly error pages -------------------------------------------
    def _error(code, title, message):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": message}), code
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def _e400(e): return _error(400, "Bad request", getattr(e, "description", "The request could not be processed."))
    @app.errorhandler(403)
    def _e403(e): return _error(403, "Forbidden", "You do not have permission to open this page.")
    @app.errorhandler(404)
    def _e404(e): return _error(404, "Page not found", "That page does not exist.")
    @app.errorhandler(413)
    def _e413(e): return _error(413, "Upload too large", "The uploaded data is too large.")
    @app.errorhandler(500)
    def _e500(e): return _error(500, "Server error", "Something went wrong. The problem was logged; nothing unsafe was shown.")

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.dashboard") if session.get("admin_id") else url_for("auth.login"))

    # Load the AI model in the background so the first webcam frame is not slow.
    if not app.config.get("TESTING") and not app.config.get("SKIP_MODEL_WARMUP"):
        def _warm():
            try:
                from models.face_recognition_model import get_engine
                get_engine().warm_up()
                app.logger.info("Face model loaded.")
                if app.config.get("AUTO_SYNC_ON_START", True):
                    from services import folder_sync_service
                    conn = database.connect(app.config["DATABASE"])
                    try:
                        rep = folder_sync_service.sync(conn, app.config["KNOWN_FACES_DIR"])
                        app.logger.info("known_faces sync: %d enrolled, %d skipped, %d failed",
                                        rep["enrolled"], rep["skipped"], rep["failed"])
                        for r in rep["results"]:
                            if r["status"] in ("enrolled", "failed"):
                                app.logger.info("  %s: %s - %s", r["label"], r["status"], r["message"])
                    finally:
                        conn.close()
            except Exception as exc:       # e.g. no internet on the very first run
                app.logger.error("Face model could not be loaded: %s", exc)
        threading.Thread(target=_warm, daemon=True).start()
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    application = create_app()
    print("\n  Face Attendance System running at  http://127.0.0.1:5000")
    print("  Default login: %s / %s  (you must change the password at first login)\n"
          % (Config.DEFAULT_ADMIN_USERNAME, Config.DEFAULT_ADMIN_PASSWORD))
    application.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
