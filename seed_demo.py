"""
seed_demo.py - enroll the sample photos in sample_images/ so you can demo without a webcam.

    python seed_demo.py                 # register + enroll Altamash and Murtaza from the photos
    python seed_demo.py --history       # ALSO add clearly-labelled DEMO attendance history for the charts

The history is ILLUSTRATIVE demo data (sessions named "[DEMO] ...", records marked as manual
with reason "demo seed data"). It is not an experimental result. Delete those sessions before real use.
"""
import argparse
import sys
from pathlib import Path

from config import Config
from database import db as database
from models.face_recognition_model import decode_image, get_engine
from services import enrollment_service as es
from services import time_utils as tu
from services.time_utils import now_utc_iso

HERE = Path(__file__).resolve().parent
PEOPLE = [
    {"student_code": "DEMO-001", "full_name": "Altamash", "department": "Computer Engineering", "class_name": "Demo Class",
     "email": "", "files": ["Altamash (1).jpeg", "Altamash (2).jpeg", "Altamash (3).jpeg", "Altamash (4).jpeg"]},
    {"student_code": "DEMO-002", "full_name": "Murtaza", "department": "Computer Engineering", "class_name": "Demo Class",
     "email": "", "files": ["Murtaza.jpeg"]},
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", action="store_true")
    args = ap.parse_args()
    tu.configure(Config.TIMEZONE)
    database.init_db(Config.DATABASE)
    database.seed_admin(Config.DATABASE, Config.DEFAULT_ADMIN_USERNAME, Config.DEFAULT_ADMIN_PASSWORD, Config.PASSWORD_HASH_METHOD)
    conn = database.connect(Config.DATABASE)
    admin = {"id": None, "username": "seed_demo"}
    print("Loading face model (first run downloads ~120 MB)...")
    get_engine().warm_up()
    ids = {}
    for p in PEOPLE:
        row = conn.execute("SELECT id FROM students WHERE student_code=?", (p["student_code"],)).fetchone()
        sid = row["id"] if row else es.create_student(conn, {k: p[k] for k in ("student_code", "full_name", "department", "class_name", "email")}, admin)
        imgs = [decode_image((HERE / "sample_images" / f).read_bytes()) for f in p["files"]]
        try:
            rep = es.enroll_images(conn, sid, imgs, admin, min_images=1)
            print(f"{p['full_name']}: {rep['accepted']} template(s) saved, {rep['rejected']} rejected")
        except es.EnrollmentError as exc:
            print(f"{p['full_name']}: enrollment failed - {exc}")
        ids[p["student_code"]] = sid
    if args.history:
        from datetime import timedelta
        today = tu.local_today()
        conn.execute("UPDATE students SET registration_date=? WHERE student_code LIKE 'DEMO-%'", ((today - timedelta(days=10)).isoformat(),))
        pattern = {"DEMO-001": [1, 1, 1, 0, 1, 1, 1, 1], "DEMO-002": [1, 0, 1, 1, 0, 1, 1, 0]}
        for i in range(8):
            d = (today - timedelta(days=8 - i)).isoformat()
            name = f"[DEMO] Lecture {i + 1}"
            if conn.execute("SELECT 1 FROM attendance_sessions WHERE name=?", (name,)).fetchone():
                continue
            cur = conn.execute("INSERT INTO attendance_sessions (name, session_date, status, started_at, ended_at) VALUES (?, ?, 'closed', ?, ?)",
                               (name, d, now_utc_iso(), now_utc_iso()))
            for code, pat in pattern.items():
                if pat[i]:
                    conn.execute("INSERT INTO attendance_records (session_id, student_id, status, source, marked_at, is_corrected, correction_reason) "
                                 "VALUES (?, ?, 'Present', 'manual', ?, 1, 'demo seed data')", (cur.lastrowid, ids[code], now_utc_iso()))
        conn.commit()
        print("Illustrative DEMO history added.")
    conn.close()
    print("Done. Start the app with: python app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
