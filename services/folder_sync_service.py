"""
services/folder_sync_service.py - "drop photos in a folder and they are enrolled".

Folder: known_faces/   (see known_faces/README.txt for the naming rules)
Nothing is trained: the pretrained model turns each photo into a 512-number template
(exactly like webcam enrollment) and the photo files are left untouched.
Privacy rules still apply: a person whose consent was WITHDRAWN is never re-enrolled.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from models.face_recognition_model import decode_image, get_engine
from services import enrollment_service as es
from services.validators import ValidationError, clean_text, validate_student_form

EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_COPY_SUFFIX = re.compile(r"(\s*\(\d+\)|_\d+)$")                  # "Ali (2)" or "Ali_2" -> "Ali"
_ID_PREFIX = re.compile(r"^([A-Za-z0-9][A-Za-z0-9\-]{1,29})__(.+)$")  # "CS-001__Murtaza"
SYSTEM_ADMIN = {"id": None, "username": "folder-sync"}


def _images_in(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTS)


def collect_groups(folder: Path) -> dict[str, list[Path]]:
    """label -> photo files. Files and sub-folders with the same label are merged."""
    groups: dict[str, list[Path]] = {}
    for p in sorted(folder.iterdir()):
        if p.is_dir():
            label, files = p.name, _images_in(p)
        elif p.is_file() and p.suffix.lower() in EXTS:
            label, files = _COPY_SUFFIX.sub("", p.stem).strip(), [p]
        else:
            continue
        if label and files:
            groups.setdefault(label, []).extend(files)
    return groups


def parse_label(label: str) -> tuple[str | None, str]:
    m = _ID_PREFIX.match(label)
    code, name = (m.group(1), m.group(2)) if m else (None, label)
    return code, clean_text(name.replace("_", " "), "Name", 2, 100)


def _next_auto_code(db: sqlite3.Connection) -> str:
    n = db.execute("SELECT COUNT(*) FROM students").fetchone()[0] + 1
    while db.execute("SELECT 1 FROM students WHERE student_code = ?", (f"F{n:03d}",)).fetchone():
        n += 1
    return f"F{n:03d}"


def sync(db: sqlite3.Connection, folder, engine=None, admin: dict | None = None, ip: str | None = None,
         force: bool = False) -> dict:
    """Enroll every person found in `folder`. Returns {'results': [...], 'enrolled': n, 'skipped': n, 'failed': n}."""
    engine = engine or get_engine()
    admin = admin or SYSTEM_ADMIN
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for label, files in collect_groups(folder).items():
        item = {"label": label, "photos": len(files), "status": "", "message": ""}
        results.append(item)
        try:
            code, name = parse_label(label)
        except ValidationError as exc:
            item.update(status="failed", message=str(exc)); continue

        if code:
            row = db.execute("SELECT * FROM students WHERE student_code = ?", (code,)).fetchone()
        else:
            row = db.execute("SELECT * FROM students WHERE lower(full_name) = lower(?) ORDER BY id LIMIT 1", (name,)).fetchone()

        created = False
        if row is not None:
            if row["consent_status"] != "granted":
                item.update(status="skipped", message="consent was withdrawn - not re-enrolled"); continue
            have = db.execute("SELECT COUNT(*) FROM face_embeddings WHERE student_id=? AND model_name=?",
                              (row["id"], engine.model_name)).fetchone()[0]
            if have and not force:
                item.update(status="skipped", message="already enrolled"); continue
            sid = row["id"]
        else:
            try:
                data = validate_student_form({"student_code": code or _next_auto_code(db), "full_name": name,
                                              "department": "General", "class_name": "General", "email": "", "consent": "on"})
                sid = es.create_student(db, data, admin, ip)
                created = True
            except (ValidationError, es.EnrollmentError) as exc:
                item.update(status="failed", message=str(exc)); continue

        try:
            imgs = [decode_image(f.read_bytes()) for f in files]
            rep = es.enroll_images(db, sid, imgs, admin, ip, min_images=1, engine=engine)
            bad = [p["reason"] for p in rep["per_image"] if not p["ok"]]
            item.update(status="enrolled", message=f"{rep['accepted']} photo(s) used" + (f"; {len(bad)} rejected ({bad[0]})" if bad else ""))
        except es.EnrollmentError as exc:
            if created:                                   # do not leave an un-enrolled stub behind
                db.execute("DELETE FROM students WHERE id = ?", (sid,)); db.commit()
            item.update(status="failed", message=str(exc))
    count = lambda s: sum(1 for r in results if r["status"] == s)
    return {"results": results, "enrolled": count("enrolled"), "skipped": count("skipped"), "failed": count("failed")}
