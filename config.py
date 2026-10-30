"""
config.py - central configuration for the Face Recognition Attendance System.

Every value can be overridden with an environment variable, so you never have
to edit the code to change the database path, timezone, model or threshold.
Values marked "editable in Settings page" are also stored in the database
(table `settings`) and the database value wins over the value in this file.
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


def _load_secret_key() -> str:
    """Use SECRET_KEY from the environment, otherwise create one once and keep it
    in instance/secret_key (never committed to Git, never served over HTTP)."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    key_file = INSTANCE_DIR / "secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    return key


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Config:
    BASE_DIR = BASE_DIR
    # ---------------------------------------------------------------- Flask
    SECRET_KEY = _load_secret_key()
    DATABASE = os.environ.get("DATABASE_PATH", str(INSTANCE_DIR / "attendance.db"))
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024          # reject request bodies > 25 MB
    SESSION_COOKIE_HTTPONLY = True                 # JavaScript cannot read the cookie
    SESSION_COOKIE_SAMESITE = "Lax"                # basic CSRF protection
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"  # set 1 behind HTTPS
    SESSION_LIFETIME_MINUTES = _env_int("SESSION_LIFETIME_MINUTES", 120)
    CSRF_ENABLED = True
    TESTING = False

    # Drop photos into this folder; people are enrolled automatically (see known_faces/README.txt)
    KNOWN_FACES_DIR = os.environ.get("KNOWN_FACES_DIR", str(BASE_DIR / "known_faces"))
    AUTO_SYNC_ON_START = os.environ.get("AUTO_SYNC_ON_START", "1") == "1"

    # ------------------------------------------------------------- Timezone
    # All timestamps are STORED in UTC and DISPLAYED / REPORTED in this zone.
    TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Karachi")

    # ----------------------------------------------------- Default administrator
    # Created only when the administrators table is empty. The user is forced to
    # change the password at first login.
    DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@12345")

    # ------------------------------------------------------ Face recognition
    # "buffalo_s" = small/fast model pack (good for CPU laptops).
    # "buffalo_l" = larger, usually more accurate, slower on CPU.
    # Embeddings are model specific: if you change the model, re-enroll people.
    FACE_MODEL_NAME = os.environ.get("FACE_MODEL_NAME", "buffalo_s")
    DETECTION_SIZE = _env_int("DETECTION_SIZE", 640)
    MAX_IMAGE_SIDE = 1280                          # larger images are shrunk first
    MAX_FACES_PER_FRAME = 10

    # --- Settings below are editable in the Settings page (stored in DB) ---
    SIMILARITY_THRESHOLD = _env_float("SIMILARITY_THRESHOLD", 0.40)  # cosine similarity
    MIN_MARGIN = _env_float("MIN_MARGIN", 0.05)    # best match must beat 2nd best person by this much
    CONFIRMATIONS_REQUIRED = _env_int("CONFIRMATIONS_REQUIRED", 2)   # consecutive matching frames
    MIN_ENROLL_IMAGES = _env_int("MIN_ENROLL_IMAGES", 3)

    # --- Enrollment image-quality limits ---
    MIN_DET_SCORE = 0.60          # detector confidence
    MIN_FACE_SIZE = 80            # pixels (shortest side of the face box)
    MIN_SHARPNESS = 25.0          # variance of Laplacian on the face crop (blur check)
    MAX_ENROLL_IMAGES = 10
    ENROLL_CONSISTENCY = 0.30     # images of one person must be at least this similar to each other

    # --------------------------------------------------------- Login security
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_MINUTES = 5
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:600000"
