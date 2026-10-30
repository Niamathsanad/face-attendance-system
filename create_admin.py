"""
create_admin.py - create an administrator, or reset a password.

    python create_admin.py --username teacher1
The password is typed hidden (not shown, not stored in shell history).
"""
import argparse
import getpass
import sys

from werkzeug.security import generate_password_hash

from config import Config
from database import db as database
from services.time_utils import now_utc_iso
from services.validators import USERNAME_RE, ValidationError, validate_password


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True)
    args = ap.parse_args()
    if not USERNAME_RE.match(args.username):
        print("Username must be 3-30 characters: letters, digits, '.', '_' or '-'."); return 1
    pw = getpass.getpass("New password: ")
    if pw != getpass.getpass("Repeat password: "):
        print("Passwords do not match."); return 1
    try:
        validate_password(pw)
    except ValidationError as exc:
        print(exc); return 1
    database.init_db(Config.DATABASE)
    conn = database.connect(Config.DATABASE)
    h = generate_password_hash(pw, method=Config.PASSWORD_HASH_METHOD)
    row = conn.execute("SELECT id FROM administrators WHERE username = ?", (args.username,)).fetchone()
    if row:
        conn.execute("UPDATE administrators SET password_hash=?, must_change_password=0 WHERE id=?", (h, row["id"]))
        print("Password updated.")
    else:
        conn.execute("INSERT INTO administrators (username, password_hash, created_at) VALUES (?, ?, ?)",
                     (args.username, h, now_utc_iso()))
        print("Administrator created.")
    conn.commit(); conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
