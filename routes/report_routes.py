"""routes/report_routes.py - report preview page and CSV / Excel downloads."""
from flask import Blueprint, Response, flash, render_template, request

from database.db import get_db
from services import enrollment_service as es
from services import reporting_service as rs
from services import time_utils as tu
from services.audit_service import log_action
from services.security import client_ip, current_admin, login_required
from services.validators import ValidationError

bp = Blueprint("reports", __name__)

_PARAMS = ("kind", "ref_date", "student_code", "department", "class_name", "date_from", "date_to")


def _params() -> dict:
    p = {k: (request.args.get(k) or "").strip()[:60] for k in _PARAMS}
    p["kind"] = p["kind"] or "day"
    p["ref_date"] = p["ref_date"] or tu.local_today_str()
    return p


@bp.route("/reports")
@login_required
def reports():
    db = get_db()
    p = _params()
    report, chart = None, None
    if request.args.get("run"):
        try:
            report = rs.build_report(db, p["kind"], p["ref_date"], p["student_code"], p["department"],
                                     p["class_name"], p["date_from"], p["date_to"])
            df = report["frame"]
            if not df.empty:
                g = df.groupby("session_date")["status"].agg(
                    present=lambda s: int((s == "Present").sum()), total="size")
                chart = {"labels": list(g.index), "present": [int(v) for v in g["present"]],
                         "absent": [int(t - pr) for pr, t in zip(g["present"], g["total"])]}
        except ValidationError as exc:
            flash(str(exc), "danger")
    return render_template("reports.html", p=p, report=report, chart=chart, groups=es.distinct_groups(db),
                           kinds=rs.REPORT_KINDS, tz=tu.tz_name())


@bp.route("/reports/export")
@login_required
def export():
    p = _params()
    fmt = (request.args.get("format") or "csv").lower()
    try:
        report = rs.build_report(get_db(), p["kind"], p["ref_date"], p["student_code"], p["department"],
                                 p["class_name"], p["date_from"], p["date_to"])
    except ValidationError as exc:
        flash(str(exc), "danger")
        return render_template("reports.html", p=p, report=None, chart=None, groups=es.distinct_groups(get_db()),
                               kinds=rs.REPORT_KINDS, tz=tu.tz_name()), 400
    admin = current_admin()
    log_action(get_db(), admin["id"], admin["username"], "report_exported", "report", p["kind"],
               {"format": fmt, "from": report["date_from"], "to": report["date_to"]}, client_ip())
    name = f"attendance_{p['kind']}_{report['date_from']}_{report['date_to']}"
    if fmt == "xlsx":
        return Response(rs.export_excel(report),
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return Response(rs.export_csv(report), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
