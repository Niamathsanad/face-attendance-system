"""services/audit_service.py - append-only audit trail of administrator actions."""
import json
import sqlite3

from services.time_utils import now_utc_iso


def log_action(db: sqlite3.Connection, admin_id, admin_username, action: str,
               entity_type: str = None, entity_id=None, details: dict = None,
               ip: str = None, commit: bool = True) -> None:
    """Write one audit row. Audit failures must never crash the main action."""
    try:
        db.execute(
            "INSERT INTO audit_logs (admin_id, admin_username, action, entity_type, entity_id, details, ip_address, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (admin_id, admin_username, action, entity_type,
             None if entity_id is None else str(entity_id),
             json.dumps(details or {}, ensure_ascii=False, default=str), ip, now_utc_iso()),
        )
        if commit:
            db.commit()
    except sqlite3.Error:
        pass


def list_logs(db: sqlite3.Connection, limit: int = 300, action: str = None):
    sql = "SELECT * FROM audit_logs"
    params: list = []
    if action:
        sql += " WHERE action = ?"
        params.append(action)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return db.execute(sql, params).fetchall()
