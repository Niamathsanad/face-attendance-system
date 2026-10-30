"""
services/attendance_service.py - sessions, attendance records, corrections, queries.

Duplicate prevention: the table attendance_records has UNIQUE(session_id, student_id).
Even if two browser tabs or two cameras send the same person at the same moment,
SQLite rejects the second INSERT and we report "already recorded".
"""
from __future__ import annotations

import json
import sqlite3

from services.dbutil import safe_rollback

import pandas as pd

from services.audit_service import log_action
from services.time_utils import local_today_str, now_utc_iso, to_local_str
from services.validators import ValidationError, clean_text, validate_session_name


class AttendanceError(Exception):
    """Safe-to-display error (database problems are translated into this)."""


# -------------------------------------------------------------------- sessions
def get_open_session(db: sqlite3.Connection):
    return db.execute("SELECT * FROM attendance_sessions WHERE status = 'open'").fetchone()


def get_session(db: sqlite3.Connection, session_id: int):
    return db.execute("SELECT * FROM attendance_sessions WHERE id = ?", (session_id,)).fetchone()


def create_session(db, name: str, department: str | None, class_name: str | None, admin: dict, ip: str = None) -> int:
    name = validate_session_name(name)
    department = clean_text(department, "Department", 1, 60) if (department or "").strip() else None
    class_name = clean_text(class_name, "Class", 1, 60) if (class_name or "").strip() else None
    if get_open_session(db) is not None:
        raise AttendanceError("A session is already open. Close it before starting a new one.")
    try:
        cur = db.execute(
            "INSERT INTO attendance_sessions (name, session_date, department, class_name, status, started_at, created_by) "
            "VALUES (?, ?, ?, ?, 'open', ?, ?)",
            (name, local_today_str(), department, class_name, now_utc_iso(), admin.get("id")))
        db.commit()
    except sqlite3.IntegrityError:
        safe_rollback(db)
        raise AttendanceError("A session is already open. Close it before starting a new one.")
    except sqlite3.Error:
        safe_rollback(db)
        raise AttendanceError("Database error while creating the session. Nothing was saved.")
    log_action(db, admin.get("id"), admin.get("username"), "session_created", "session", cur.lastrowid,
               {"name": name, "department": department, "class": class_name}, ip)
    return cur.lastrowid


def close_session(db, session_id: int, admin: dict, ip: str = None) -> None:
    row = get_session(db, session_id)
    if row is None:
        raise AttendanceError("Session not found.")
    if row["status"] != "open":
        raise AttendanceError("This session is already closed.")
    try:
        db.execute("UPDATE attendance_sessions SET status='closed', ended_at=? WHERE id=?", (now_utc_iso(), session_id))
        db.commit()
    except sqlite3.Error:
        safe_rollback(db)
        raise AttendanceError("Database error while closing the session.")
    log_action(db, admin.get("id"), admin.get("username"), "session_closed", "session", session_id, {"name": row["name"]}, ip)


def student_in_session_scope(session, person: dict) -> bool:
    """person needs keys department/class_name (dict or sqlite Row)."""
    if session["department"] and session["department"] != person["department"]:
        return False
    if session["class_name"] and session["class_name"] != person["class_name"]:
        return False
    return True


def record_exists(db, session_id: int, student_id: int) -> bool:
    return db.execute("SELECT 1 FROM attendance_records WHERE session_id=? AND student_id=?",
                      (session_id, student_id)).fetchone() is not None


# --------------------------------------------------------------------- records
def mark_present(db, session_id: int, student_id: int, confidence: float | None = None,
                 source: str = "face") -> str:
    """Insert a Present record. Returns 'marked' or 'already'. Raises AttendanceError on DB trouble."""
    try:
        db.execute(
            "INSERT INTO attendance_records (session_id, student_id, status, source, marked_at, confidence) "
            "VALUES (?, ?, 'Present', ?, ?, ?)",
            (session_id, student_id, source, now_utc_iso(), confidence))
        db.commit()
        return "marked"
    except sqlite3.IntegrityError as exc:
        safe_rollback(db)
        if "UNIQUE" in str(exc).upper():
            return "already"                       # duplicate blocked by the database constraint
        raise AttendanceError("Could not save attendance (data integrity problem).")
    except sqlite3.Error:
        safe_rollback(db)
        raise AttendanceError("Database error - attendance was not saved. Please try again.")


def correct_record(db, session_id: int, student_id: int, new_status: str, reason: str,
                   admin: dict, ip: str = None) -> str:
    """Manually set Present/Absent. Keeps the original value and writes an audit row."""
    if new_status not in ("Present", "Absent"):
        raise ValidationError("Status must be Present or Absent.")
    reason = clean_text(reason, "Reason", 3, 200)
    session = get_session(db, session_id)
    student = db.execute("SELECT id, student_code FROM students WHERE id=?", (student_id,)).fetchone()
    if session is None or student is None:
        raise AttendanceError("Session or student not found.")
    existing = db.execute("SELECT * FROM attendance_records WHERE session_id=? AND student_id=?",
                          (session_id, student_id)).fetchone()
    old = existing["status"] if existing else "Absent"        # no record == Absent
    if old == new_status:
        raise ValidationError(f"Student is already {new_status}. No change made.")
    now = now_utc_iso()
    try:
        if existing:
            db.execute(
                "UPDATE attendance_records SET status=?, is_corrected=1, "
                "original_status=COALESCE(original_status, ?), corrected_by=?, corrected_at=?, correction_reason=? "
                "WHERE id=?", (new_status, existing["status"], admin.get("id"), now, reason, existing["id"]))
        else:
            db.execute(
                "INSERT INTO attendance_records (session_id, student_id, status, source, marked_at, is_corrected, "
                "original_status, corrected_by, corrected_at, correction_reason) "
                "VALUES (?, ?, ?, 'manual', ?, 1, NULL, ?, ?, ?)",
                (session_id, student_id, new_status, now, admin.get("id"), now, reason))
        db.commit()
    except sqlite3.Error:
        safe_rollback(db)
        raise AttendanceError("Database error - the correction was not saved.")
    log_action(db, admin.get("id"), admin.get("username"), "attendance_corrected", "attendance",
               f"{session_id}:{student['student_code']}",
               {"session_id": session_id, "student": student["student_code"], "from": old, "to": new_status,
                "reason": reason}, ip)
    return new_status


# --------------------------------------------------------------------- queries
MATRIX_SQL = """
SELECT s.id AS session_id, s.session_date, s.name AS session_name, s.status AS session_status,
       st.id AS student_id, st.student_code, st.full_name, st.department, st.class_name,
       COALESCE(a.status, 'Absent') AS status,
       a.source, a.marked_at, a.confidence,
       COALESCE(a.is_corrected, 0) AS is_corrected, a.original_status, a.correction_reason,
       CASE WHEN a.id IS NULL THEN 0 ELSE 1 END AS has_record
FROM attendance_sessions s
JOIN students st
  ON ( st.registration_date <= s.session_date
       AND (s.department IS NULL OR st.department = s.department)
       AND (s.class_name IS NULL OR st.class_name = s.class_name) )
  OR EXISTS (SELECT 1 FROM attendance_records x WHERE x.session_id = s.id AND x.student_id = st.id)
LEFT JOIN attendance_records a ON a.session_id = s.id AND a.student_id = st.id
WHERE 1 = 1
"""


def attendance_matrix(db, date_from: str = None, date_to: str = None, department: str = None,
                      class_name: str = None, student_code: str = None, session_id: int = None,
                      search: str = None, status: str = None) -> pd.DataFrame:
    """One row per (session, expected student). The single source for tables, stats and reports.

    "Expected" = student registered on/before the session date and inside the session's
    department/class scope (or already has a record). No record means Absent.
    """
    sql, params = MATRIX_SQL, []
    if date_from:
        sql += " AND s.session_date >= ?"; params.append(date_from)
    if date_to:
        sql += " AND s.session_date <= ?"; params.append(date_to)
    if department:
        sql += " AND st.department = ?"; params.append(department)
    if class_name:
        sql += " AND st.class_name = ?"; params.append(class_name)
    if student_code:
        sql += " AND st.student_code = ?"; params.append(student_code)
    if session_id:
        sql += " AND s.id = ?"; params.append(session_id)
    if search:
        like = f"%{search.strip()}%"
        sql += " AND (st.student_code LIKE ? OR st.full_name LIKE ?)"; params += [like, like]
    if status in ("Present", "Absent"):
        sql += " AND COALESCE(a.status, 'Absent') = ?"; params.append(status)
    sql += " ORDER BY s.session_date DESC, s.id DESC, st.full_name"
    rows = db.execute(sql, params).fetchall()
    cols = ["session_id", "session_date", "session_name", "session_status", "student_id", "student_code",
            "full_name", "department", "class_name", "status", "source", "marked_at", "confidence",
            "is_corrected", "original_status", "correction_reason", "has_record"]
    df = pd.DataFrame([tuple(r) for r in rows], columns=cols)
    df["record_type"] = df.apply(_record_type, axis=1) if len(df) else pd.Series(dtype=str)
    df["marked_local"] = df["marked_at"].map(lambda v: to_local_str(v) if isinstance(v, str) else "")
    return df


def _record_type(row) -> str:
    """Clearly separates actually-recorded attendance from manual corrections."""
    if not row["has_record"]:
        return "No record"
    if row["is_corrected"] or row["source"] == "manual":
        return "Manual correction"
    return "Recorded by camera"


def summarize(df: pd.DataFrame) -> dict:
    total = len(df)
    present = int((df["status"] == "Present").sum()) if total else 0
    return {"expected": total, "present": present, "absent": total - present,
            "percentage": round(100.0 * present / total, 1) if total else None}


def student_percentages(df: pd.DataFrame) -> pd.DataFrame:
    """Attendance percentage per student: sessions attended / sessions expected."""
    cols = ["student_code", "full_name", "department", "class_name", "sessions", "present", "absent", "percentage"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    g = df.groupby(["student_code", "full_name", "department", "class_name"], as_index=False).agg(
        sessions=("status", "size"), present=("status", lambda s: int((s == "Present").sum())))
    g["absent"] = g["sessions"] - g["present"]
    g["percentage"] = (100.0 * g["present"] / g["sessions"]).round(1)
    return g[cols].sort_values("full_name")
