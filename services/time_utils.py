"""
services/time_utils.py - ONE place that decides how time is stored and shown.

Rule: timestamps are stored in UTC (ISO-8601 text) and converted to the
configured timezone (config.TIMEZONE, default Asia/Karachi) for display,
for the "session_date" and for report exports.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_tz_name = "Asia/Karachi"
_tz = ZoneInfo(_tz_name)


def configure(tz_name: str) -> None:
    """Called once at start-up. Falls back to UTC if the name is invalid."""
    global _tz, _tz_name
    try:
        _tz = ZoneInfo(tz_name)
        _tz_name = tz_name
    except Exception:
        _tz, _tz_name = timezone.utc, "UTC"


def tz_name() -> str:
    return _tz_name


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc_iso() -> str:
    return now_utc().strftime("%Y-%m-%dT%H:%M:%S+00:00")


def local_now() -> datetime:
    return now_utc().astimezone(_tz)


def local_today() -> date:
    return local_now().date()


def local_today_str() -> str:
    return local_today().isoformat()


def to_local_str(iso_utc: str | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Convert a stored UTC ISO string to a local-time string for humans."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
    except ValueError:
        return str(iso_utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz).strftime(fmt)


def parse_date(value: str | None) -> date | None:
    """Parse 'YYYY-MM-DD'. Returns None for empty or invalid input."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def week_bounds(d: date) -> tuple[date, date]:
    """Monday..Sunday of the week containing d."""
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def month_bounds(d: date) -> tuple[date, date]:
    start = d.replace(day=1)
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, nxt - timedelta(days=1)
