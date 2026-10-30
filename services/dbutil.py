"""services/dbutil.py - tiny database helpers."""
import sqlite3


def safe_rollback(db: sqlite3.Connection) -> None:
    """Roll back, but never raise (the connection itself may already be broken)."""
    try:
        db.rollback()
    except sqlite3.Error:
        pass
