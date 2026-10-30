"""routes/attendance_routes.py - sessions, live recognition API, attendance records, corrections, audit."""
from flask import (Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for)

from database.db import get_db
from models.face_recognition_model import decode_image
from services import attendance_service as att
from services import audit_service
from services import enrollment_service as es
from services import recognition_service as rec
from services import security
from services import time_utils as tu
from services.security import current_admin, login_required
from services.validators import ValidationError

bp = Blueprint("attendance", __name__)


# ---------------------------------------------------------------- sessions
@bp.route("/sessions")
@login_required
def sessions():
    db = get_db()
    rows = db.execute("SELECT * FROM attendance_sessions ORDER BY id DESC LIMIT 50").fetchall()
    stats = {}
    if rows:
        df = att.attendance_matrix(db, date_from=min(r["session_date"] for r in rows))
        for sid, sub in df.groupby("session_id"):
            stats[int(sid)] = att.summarize(sub)
    return render_template("sessions.html", rows=rows, stats=stats, groups=es.distinct_groups(db),
                           today=tu.local_today_str())


@bp.route("/sessions/create", methods=["POST"])
@login_required
def create_session():
    try:
        att.create_session(get_db(), request.form.get("name"), request.form.get("department"),
                           request.form.get("class_name"), current_admin(), security.client_ip())
        flash("Session started. Attendance can now be recorded.", "success")
        return redirect(url_for("attendance.live"))
    except (ValidationError, att.AttendanceError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("attendance.sessions"))


@bp.route("/sessions/<int:session_id>/close", methods=["POST"])
@login_required
def close_session(session_id):
    try:
        att.close_session(get_db(), session_id, current_admin(), security.client_ip())
        rec.tracker.reset()
        flash("Session closed.", "success")
    except att.AttendanceError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("attendance.sessions"))


# --------------------------------------------------------- live recognition
@bp.route("/live")
@login_required
def live():
    return render_template("live_recognition.html", session_row=att.get_open_session(get_db()))


@bp.route("/api/recognize", methods=["POST"])
@login_required
def api_recognize():
    import base64
    data = request.get_json(silent=True) or {}
    b64 = data.get("image") or ""
    try:
        b64 = b64.split(",", 1)[1] if "," in b64 else b64
        frame = decode_image(base64.b64decode(b64), current_app.config["MAX_IMAGE_SIDE"])
    except Exception:
        frame = None
    if frame is None:
        return jsonify({"ok": False, "error": "Could not read the camera frame."}), 400
    db = get_db()
    session_row = att.get_open_session(db)
    try:
        result = rec.process_frame(db, frame, session_row, max_faces=current_app.config["MAX_FACES_PER_FRAME"])
    except RuntimeError as exc:
        current_app.logger.error("Face model problem: %s", exc)
        return jsonify({"ok": False, "error": "Face model is not available yet. It may still be downloading/loading - retry in a moment."}), 503
    except Exception:
        current_app.logger.exception("Recognition failed")
        return jsonify({"ok": False, "error": "Recognition failed on the server. No attendance was recorded."}), 500
    sess = None
    if session_row is not None:
        sess = {"id": session_row["id"], "name": session_row["name"], "department": session_row["department"],
                "class_name": session_row["class_name"]}
    return jsonify({"ok": True, "session": sess, **result})


# ------------------------------------------------------ attendance records
@bp.route("/attendance")
@login_required
def records():
    db = get_db()
    today = tu.local_today_str()
    d_from = tu.parse_date(request.args.get("date_from")) or tu.parse_date(request.args.get("date")) or tu.parse_date(today)
    d_to = tu.parse_date(request.args.get("date_to")) or d_from
    if d_from > d_to:
        flash("Start date was after end date - the dates were swapped.", "warning")
        d_from, d_to = d_to, d_from
    dep = request.args.get("department") or None
    cls = request.args.get("class_name") or None
    status = request.args.get("status") or None
    q = (request.args.get("q") or "").strip()[:60]
    sid = request.args.get("session_id", type=int)
    df = att.attendance_matrix(db, d_from.isoformat(), d_to.isoformat(), dep, cls, None, sid, q or None, status)
    full = att.attendance_matrix(db, d_from.isoformat(), d_to.isoformat(), dep, cls, None, sid, q or None)
    sessions_in_range = db.execute(
        "SELECT id, name, session_date FROM attendance_sessions WHERE session_date BETWEEN ? AND ? ORDER BY id DESC",
        (d_from.isoformat(), d_to.isoformat())).fetchall()
    return render_template("attendance.html", rows=df.to_dict("records"), summary=att.summarize(full),
                           percentages=att.student_percentages(full).to_dict("records"),
                           groups=es.distinct_groups(db), sessions_in_range=sessions_in_range,
                           f={"date_from": d_from.isoformat(), "date_to": d_to.isoformat(), "department": dep or "",
                              "class_name": cls or "", "status": status or "", "q": q, "session_id": sid or ""})


@bp.route("/attendance/correct", methods=["POST"])
@login_required
def correct():
    nxt = request.form.get("next")
    back = nxt if security.is_safe_next(nxt) else url_for("attendance.records")
    try:
        att.correct_record(get_db(), request.form.get("session_id", type=int) or 0,
                           request.form.get("student_id", type=int) or 0,
                           request.form.get("status", ""), request.form.get("reason", ""),
                           current_admin(), security.client_ip())
        flash("Attendance corrected and recorded in the audit log.", "success")
    except (ValidationError, att.AttendanceError) as exc:
        flash(str(exc), "danger")
    return redirect(back)


# ------------------------------------------------------------------- audit
@bp.route("/audit")
@login_required
def audit():
    return render_template("audit.html", rows=audit_service.list_logs(get_db(), 300, request.args.get("action") or None))
