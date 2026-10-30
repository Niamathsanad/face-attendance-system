"""services/settings_service.py - runtime settings: DB value wins, otherwise config.py default."""
import sqlite3

from config import Config
from services.time_utils import now_utc_iso
from services.validators import ValidationError

# key -> (type, min, max, default taken from Config)
SETTING_SPECS = {
    "similarity_threshold": (float, 0.20, 0.90, Config.SIMILARITY_THRESHOLD),
    "min_margin": (float, 0.0, 0.50, Config.MIN_MARGIN),
    "confirmations_required": (int, 1, 5, Config.CONFIRMATIONS_REQUIRED),
    "min_enroll_images": (int, 1, 10, Config.MIN_ENROLL_IMAGES),
}


def get_setting(db: sqlite3.Connection, key: str):
    typ, _lo, _hi, default = SETTING_SPECS[key]
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return typ(row["value"])
    except (TypeError, ValueError):
        return default


def get_all(db: sqlite3.Connection) -> dict:
    return {k: get_setting(db, k) for k in SETTING_SPECS}


def set_setting(db: sqlite3.Connection, key: str, raw_value) -> None:
    if key not in SETTING_SPECS:
        raise ValidationError("Unknown setting.")
    typ, lo, hi, _default = SETTING_SPECS[key]
    try:
        value = typ(raw_value)
    except (TypeError, ValueError):
        raise ValidationError(f"{key.replace('_', ' ').title()} must be a number.")
    if not (lo <= value <= hi):
        raise ValidationError(f"{key.replace('_', ' ').title()} must be between {lo} and {hi}.")
    db.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, str(value), now_utc_iso()),
    )
