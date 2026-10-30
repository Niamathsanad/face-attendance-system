"""
database/db.py - SQLite connection handling and first-run setup.

* connect(path)   -> plain connection, usable from scripts and background threads
* get_db()        -> one connection per Flask request (stored in flask.g)
* init_db(path)   -> creates tables from schema.sql
* seed_admin(...) -> creates the first administrator when none exists

All SQL in this project uses "?" placeholders (parameterised queries), so user
input can never be executed as SQL (protects against SQL injection).
"""
import sqlite3
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash

from services.time_utils import now_utc_iso

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    """Open a SQLite connection with safe defaults."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")      # enforce FOREIGN KEY + ON DELETE CASCADE
    conn.execute("PRAGMA secure_delete = ON")     # overwrite deleted data (deleted biometrics are wiped)
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")  # readers do not block the writer
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(path: str) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def seed_admin(path: str, username: str, password: str, method: str,
               must_change: bool = True) -> bool:
    """Create the first administrator if the table is empty. Returns True if created."""
    conn = connect(path)
    try:
        if conn.execute("SELECT COUNT(*) FROM administrators").fetchone()[0] > 0:
            return False
        conn.execute(
            "INSERT INTO administrators (username, password_hash, full_name, must_change_password, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, generate_password_hash(password, method=method), "System Administrator",
             1 if must_change else 0, now_utc_iso()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    init_db(app.config["DATABASE"])
    seed_admin(app.config["DATABASE"], app.config["DEFAULT_ADMIN_USERNAME"],
               app.config["DEFAULT_ADMIN_PASSWORD"], app.config["PASSWORD_HASH_METHOD"])
