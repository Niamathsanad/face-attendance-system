"""
add_person.py - add a person + enroll their face from photo files (no webcam, no code editing).

Examples (PowerShell, inside the project folder, venv active):
  python add_person.py --id CS-001 --name "Murtaza" --photos "C:\\Users\\Admin\\Desktop\\Murtaza.jpg"
  python add_person.py --id CS-002 --name "Niamatullah Hasand" --dept "Computer Engineering" --class "Sem-5" --photos "C:\\pics\\Nia1.jpg" "C:\\pics\\Nia2.jpg"
  python add_person.py --id CS-003 --name "Ali" --folder "C:\\pics\\Ali"      (uses every image in that folder)

More photos (3-5, different angles/lighting) = better recognition. One photo works but is weaker.
IMPORTANT: stop and restart `python app.py` afterwards so the running app loads the new face.
By running this you confirm the person has given consent to store their face template.
"""
import argparse
import sys
from pathlib import Path

from config import Config
from database import db as database
from models.face_recognition_model import decode_image, get_engine
from services import enrollment_service as es
from services import time_utils as tu
from services.validators import ValidationError, validate_student_form

EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="unique ID, e.g. CS-001")
    ap.add_argument("--name", required=True)
    ap.add_argument("--dept", default="General")
    ap.add_argument("--class", dest="cls", default="General")
    ap.add_argument("--email", default="")
    ap.add_argument("--photos", nargs="*", default=[], help="one or more image files")
    ap.add_argument("--folder", help="folder containing the person's photos")
    args = ap.parse_args()

    files = [Path(p) for p in args.photos]
    if args.folder:
        files += sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in EXTS)
    files = [f for f in files if f.suffix.lower() in EXTS]
    if not files:
        print("ERROR: no image files found. Give --photos file1 file2 ... or --folder."); return 1
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        print("ERROR: file(s) not found:\n  " + "\n  ".join(missing)); return 1

    tu.configure(Config.TIMEZONE)
    database.init_db(Config.DATABASE)
    conn = database.connect(Config.DATABASE)
    admin = {"id": None, "username": "add_person.py"}
    try:
        data = validate_student_form({"student_code": args.id, "full_name": args.name, "department": args.dept,
                                      "class_name": args.cls, "email": args.email, "consent": "on"})
        row = conn.execute("SELECT id FROM students WHERE student_code = ?", (data["student_code"],)).fetchone()
        sid = row["id"] if row else es.create_student(conn, data, admin)
        print("Loading face model (first run downloads ~120 MB)...")
        get_engine().warm_up()
        imgs = [decode_image(f.read_bytes()) for f in files]
        rep = es.enroll_images(conn, sid, imgs, admin, min_images=1)
    except (ValidationError, es.EnrollmentError) as exc:
        print("ERROR:", exc); return 1
    finally:
        conn.close()
    for p, f in zip(rep["per_image"], files):
        print(f"  {f.name}: {'accepted' if p['ok'] else 'REJECTED - ' + p['reason']}")
    print(f"Done: {args.name} ({args.id}) enrolled with {rep['accepted']} template(s).")
    print("Now restart the app (Ctrl+C, then python app.py).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
