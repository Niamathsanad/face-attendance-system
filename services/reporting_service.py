"""
services/reporting_service.py - dashboard statistics, report building, CSV/Excel export.

Every number shown on the dashboard comes from SQL queries through
attendance_service.attendance_matrix(); nothing is hard-coded.
Timestamps are shown in the configured timezone (see services/time_utils.py).
"""
from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd

from services import attendance_service as att
from services import time_utils as tu
from services.validators import ValidationError

REPORT_COLUMNS = ["Date", "Session", "Student ID", "Name", "Department", "Class", "Status",
                  "Record Type", "Marked At", "Confidence", "Correction Reason"]


# ------------------------------------------------------------------- dashboard
def dashboard_stats(db) -> dict:
    today = tu.local_today_str()
    total = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    enrolled = db.execute("SELECT COUNT(DISTINCT student_id) FROM face_embeddings").fetchone()[0]
    df = att.attendance_matrix(db, date_from=today, date_to=today)
    open_session = att.get_open_session(db)
    if df.empty:
        present = absent = 0
        pct = None
    else:
        by_student = df.groupby("student_id")["status"].agg(lambda s: (s == "Present").any())
        present = int(by_student.sum())
        absent = int(len(by_student) - present)
        pct = round(100.0 * present / len(by_student), 1)
    return {"total_registered": total, "face_enrolled": enrolled, "present_today": present,
            "absent_today": absent, "percentage_today": pct, "sessions_today": int(df["session_id"].nunique()) if not df.empty else 0,
            "open_session": open_session["name"] if open_session else None, "date": today, "timezone": tu.tz_name()}


def recent_records(db, limit: int = 10) -> list[dict]:
    rows = db.execute(
        "SELECT s.student_code, s.full_name, a.status, a.source, a.is_corrected, a.marked_at, a.confidence, ss.name AS session_name "
        "FROM attendance_records a JOIN students s ON s.id = a.student_id "
        "JOIN attendance_sessions ss ON ss.id = a.session_id ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        kind = "Manual correction" if (r["is_corrected"] or r["source"] == "manual") else "Recorded by camera"
        out.append({"student_code": r["student_code"], "name": r["full_name"], "status": r["status"],
                    "type": kind, "time": tu.to_local_str(r["marked_at"]), "session": r["session_name"],
                    "confidence": None if r["confidence"] is None else round(r["confidence"], 3)})
    return out


def _series(df: pd.DataFrame, keys: list[str], labels: list[str]) -> dict:
    """Pooled attendance per period: present marks / expected marks."""
    present, expected, rate = [], [], []
    g = {}
    if not df.empty:
        for k, sub in df.groupby("_period"):
            g[k] = (int((sub["status"] == "Present").sum()), len(sub))
    for k in keys:
        p, e = g.get(k, (0, 0))
        present.append(p); expected.append(e)
        rate.append(round(100.0 * p / e, 1) if e else None)
    return {"labels": labels, "present": present, "absent": [e - p for p, e in zip(present, expected)],
            "expected": expected, "percentage": rate}


def daily_series(db, days: int = 14) -> dict:
    end = tu.local_today()
    start = end - timedelta(days=days - 1)
    df = att.attendance_matrix(db, date_from=start.isoformat(), date_to=end.isoformat())
    if not df.empty:
        df["_period"] = df["session_date"]
    keys = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    return _series(df, keys, [k[5:] for k in keys])


def weekly_series(db, weeks: int = 8) -> dict:
    this_monday, _ = tu.week_bounds(tu.local_today())
    start = this_monday - timedelta(weeks=weeks - 1)
    df = att.attendance_matrix(db, date_from=start.isoformat(), date_to=tu.local_today_str())
    if not df.empty:
        df["_period"] = df["session_date"].map(lambda s: tu.week_bounds(date.fromisoformat(s))[0].isoformat())
    keys = [(start + timedelta(weeks=i)).isoformat() for i in range(weeks)]
    return _series(df, keys, ["Wk " + k[5:] for k in keys])


def monthly_series(db, months: int = 6) -> dict:
    t = tu.local_today()
    first_months = []
    y, m = t.year, t.month
    for _ in range(months):
        first_months.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    first_months.reverse()
    df = att.attendance_matrix(db, date_from=first_months[0].isoformat(), date_to=t.isoformat())
    if not df.empty:
        df["_period"] = df["session_date"].str[:7]
    keys = [d.strftime("%Y-%m") for d in first_months]
    return _series(df, keys, [d.strftime("%b %Y") for d in first_months])


# --------------------------------------------------------------------- reports
REPORT_KINDS = {"day": "Daily report", "week": "Weekly report", "month": "Monthly report",
                "student": "Student / employee report", "group": "Department / class report"}


def resolve_period(kind: str, ref_date: str | None) -> tuple[str, str]:
    d = tu.parse_date(ref_date) or tu.local_today()
    if kind == "week":
        a, b = tu.week_bounds(d)
    elif kind == "month":
        a, b = tu.month_bounds(d)
    else:
        a = b = d
    return a.isoformat(), b.isoformat()


def build_report(db, kind: str, ref_date: str = None, student_code: str = None, department: str = None,
                 class_name: str = None, date_from: str = None, date_to: str = None) -> dict:
    if kind not in REPORT_KINDS:
        raise ValidationError("Unknown report type.")
    if kind in ("day", "week", "month"):
        date_from, date_to = resolve_period(kind, ref_date)
    else:                                              # student / group: explicit range, default = last 30 days
        end = tu.parse_date(date_to) or tu.local_today()
        start = tu.parse_date(date_from) or (end - timedelta(days=29))
        if start > end:
            raise ValidationError("Start date must not be after the end date.")
        date_from, date_to = start.isoformat(), end.isoformat()
    if kind == "student":
        if not (student_code or "").strip():
            raise ValidationError("Enter a student / employee ID for this report.")
        row = db.execute("SELECT 1 FROM students WHERE student_code = ?", (student_code.strip(),)).fetchone()
        if row is None:
            raise ValidationError(f"No registered person with ID '{student_code}'.")
    if kind == "group" and not (department or class_name):
        raise ValidationError("Choose a department and/or a class for this report.")
    df = att.attendance_matrix(db, date_from=date_from, date_to=date_to,
                               department=department or None, class_name=class_name or None,
                               student_code=(student_code or "").strip() or None)
    table = to_report_table(df)
    return {"kind": kind, "title": REPORT_KINDS[kind], "date_from": date_from, "date_to": date_to,
            "frame": df, "table": table, "summary": att.summarize(df),
            "per_student": att.student_percentages(df), "timezone": tu.tz_name()}


def _safe_cell(v):
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def to_report_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS)
    t = pd.DataFrame({
        "Date": df["session_date"], "Session": df["session_name"], "Student ID": df["student_code"],
        "Name": df["full_name"], "Department": df["department"], "Class": df["class_name"],
        "Status": df["status"], "Record Type": df["record_type"],
        f"Marked At": df["marked_local"],
        "Confidence": df["confidence"].map(lambda v: "" if pd.isna(v) else round(float(v), 3)),
        "Correction Reason": df["correction_reason"].map(lambda v: "" if pd.isna(v) else v),
    })
    for c in ("Session", "Student ID", "Name", "Department", "Class", "Correction Reason"):
        t[c] = t[c].map(_safe_cell)
    return t[REPORT_COLUMNS]


def export_csv(report: dict) -> bytes:
    t = report["table"].rename(columns={"Marked At": f"Marked At ({report['timezone']})"})
    return t.to_csv(index=False).encode("utf-8-sig")        # BOM so Excel opens UTF-8 correctly


def export_excel(report: dict) -> bytes:
    buf = io.BytesIO()
    s = report["summary"]
    info = pd.DataFrame({"Item": ["Report", "Period", "Timezone", "Expected attendances", "Present", "Absent", "Attendance %"],
                         "Value": [report["title"], f"{report['date_from']} to {report['date_to']}", report["timezone"],
                                   s["expected"], s["present"], s["absent"],
                                   "" if s["percentage"] is None else s["percentage"]]})
    per = report["per_student"].copy()
    for c in ("student_code", "full_name", "department", "class_name"):
        per[c] = per[c].map(_safe_cell)
    per.columns = ["Student ID", "Name", "Department", "Class", "Sessions", "Present", "Absent", "Attendance %"]
    table = report["table"].rename(columns={"Marked At": f"Marked At ({report['timezone']})"})
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        info.to_excel(xw, sheet_name="Summary", index=False)
        table.to_excel(xw, sheet_name="Attendance", index=False)
        per.to_excel(xw, sheet_name="Per student", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
                ws.column_dimensions[col[0].column_letter].width = min(width + 2, 45)
    return buf.getvalue()
