"""routes/dashboard_routes.py - dashboard page and its JSON data endpoint."""
from flask import Blueprint, jsonify, render_template

from database.db import get_db
from services import reporting_service as rs
from services.security import login_required

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", stats=rs.dashboard_stats(get_db()))


@bp.route("/api/dashboard")
@login_required
def api_dashboard():
    db = get_db()
    return jsonify({"ok": True, "stats": rs.dashboard_stats(db), "recent": rs.recent_records(db, 10),
                    "daily": rs.daily_series(db, 14), "weekly": rs.weekly_series(db, 8),
                    "monthly": rs.monthly_series(db, 6)})
