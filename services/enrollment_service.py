"""
services/enrollment_service.py - register people and store their face embeddings.

Privacy design
  * Only embeddings (512 numbers) are stored. The captured photos are held in memory
    during the request and then discarded - no image is ever written to disk.
  * Enrollment is refused without recorded consent.
  * "Delete biometric data" removes every embedding for a person (consent withdrawn).
  * "Delete person" removes the person, embeddings and attendance history (cascade).
"""
from __future__ import annotations

import sqlite3

from services.dbutil import safe_rollback

import numpy as np

from config import Config
from models.face_recognition_model import embedding_to_blob, get_engine
from services import recognition_service as rec
from services.audit_service import log_action
from services.settings_service import get_setting
from services.time_utils import local_today_str, now_utc_iso
from services.validators import ValidationError


class EnrollmentError(Exception):
    """Safe-to-display enrollment problem."""


# ------------------------------------------------------------------- students
def create_student(db, data: dict, admin: dict, ip: str = None) -> int:
    now = now_utc_iso()
    try:
        cur = db.execute(
            "INSERT INTO students (student_code, full_name, department, class_name, email, registration_date, "
            "consent_status, consent_date, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'granted', ?, ?, ?)",
            (data["student_code"], data["full_name"], data["department"], data["class_name"], data["email"],
             local_today_str(), now, now, now))
        db.commit()
    except sqlite3.IntegrityError:
        safe_rollback(db)
        raise ValidationError(f"ID '{data['student_code']}' is already registered. IDs must be unique.")
    except sqlite3.Error:
        safe_rollback(db)
        raise EnrollmentError("Database error - the person was not registered.")
    log_action(db, admin.get("id"), admin.get("username"), "student_registered", "student",
               data["student_code"], {"department": data["department"], "class": data["class_name"]}, ip)
    return cur.lastrowid


def get_student(db, student_id: int):
    return db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()


def list_students(db, search: str = None, department: str = None, class_name: str = None):
    sql = ("SELECT s.*, (SELECT COUNT(*) FROM face_embeddings e WHERE e.student_id = s.id AND e.model_name = ?) AS templates "
           "FROM students s WHERE 1=1")
    params: list = [get_engine().model_name]
    if search:
        sql += " AND (s.student_code LIKE ? OR s.full_name LIKE ?)"
        params += [f"%{search.strip()}%"] * 2
    if department:
        sql += " AND s.department = ?"; params.append(department)
    if class_name:
        sql += " AND s.class_name = ?"; params.append(class_name)
    sql += " ORDER BY s.full_name"
    return db.execute(sql, params).fetchall()


def distinct_groups(db) -> dict:
    deps = [r[0] for r in db.execute("SELECT DISTINCT department FROM students ORDER BY department")]
    classes = [r[0] for r in db.execute("SELECT DISTINCT class_name FROM students ORDER BY class_name")]
    return {"departments": deps, "classes": classes}


# ----------------------------------------------------------------- enrollment
def assess_face(face) -> str | None:
    """Return a human reason if this face is not good enough, else None."""
    if face.det_score < Config.MIN_DET_SCORE:
        return f"face detection confidence too low ({face.det_score:.2f})"
    if face.size < Config.MIN_FACE_SIZE:
        return f"face too small ({face.size}px) - move closer to the camera"
    if face.sharpness < Config.MIN_SHARPNESS:
        return "image is blurry - hold still and improve lighting"
    return None


def enroll_images(db, student_id: int, images: list[np.ndarray], admin: dict, ip: str = None,
                  replace: bool = True, min_images: int | None = None, engine=None) -> dict:
    """Validate images, create embeddings, store them. Returns a report for the UI."""
    engine = engine or get_engine()
    student = get_student(db, student_id)
    if student is None:
        raise EnrollmentError("Person not found.")
    if student["consent_status"] != "granted":
        raise EnrollmentError("Consent is not granted for this person - face data cannot be collected.")
    if not images:
        raise EnrollmentError("No images received.")
    if len(images) > Config.MAX_ENROLL_IMAGES:
        raise EnrollmentError(f"Too many images (maximum {Config.MAX_ENROLL_IMAGES}).")
    min_images = min_images or int(get_setting(db, "min_enroll_images"))

    per_image, good = [], []           # good = (index, face)
    for i, img in enumerate(images):
        if img is None:
            per_image.append({"index": i, "ok": False, "reason": "not a readable image"})
            continue
        faces = engine.analyze(img)
        if len(faces) == 0:
            per_image.append({"index": i, "ok": False, "reason": "no face detected"}); continue
        if len(faces) > 1:
            per_image.append({"index": i, "ok": False, "reason": "more than one face in the picture"}); continue
        problem = assess_face(faces[0])
        if problem:
            per_image.append({"index": i, "ok": False, "reason": problem}); continue
        per_image.append({"index": i, "ok": True, "reason": "accepted"})
        good.append((i, faces[0]))

    # --- all images of one person must look alike (catches two different people in one session) ---
    if len(good) >= 2:
        E = np.vstack([f.embedding for _, f in good])
        sims = E @ E.T
        mean_other = (sims.sum(axis=1) - 1.0) / (len(good) - 1)
        keep = []
        for (i, f), m in zip(good, mean_other):
            if m < Config.ENROLL_CONSISTENCY:
                per_image[i].update(ok=False, reason="does not look like the other captured images")
            else:
                keep.append((i, f))
        good = keep

    if len(good) < min_images:
        raise EnrollmentError(
            f"Only {len(good)} usable image(s); at least {min_images} are required. "
            + "; ".join(f"image {r['index'] + 1}: {r['reason']}" for r in per_image if not r["ok"]))

    # --- refuse if this face already belongs to a DIFFERENT registered person ---
    gallery = rec.load_gallery(db, engine.model_name)
    threshold = float(get_setting(db, "similarity_threshold"))
    if not gallery.empty:
        for _, f in good:
            m = rec.match_embedding(f.embedding, gallery, threshold, 0.0)
            if m.person is not None and m.person["id"] != student_id:
                raise EnrollmentError(
                    f"This face already matches registered person {m.person['code']} ({m.person['name']}). "
                    "The same person cannot be enrolled under two IDs.")

    now = now_utc_iso()
    try:
        if replace:
            db.execute("DELETE FROM face_embeddings WHERE student_id = ?", (student_id,))
        for _, f in good:
            db.execute(
                "INSERT INTO face_embeddings (student_id, embedding, embedding_dim, model_name, quality_score, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (student_id, embedding_to_blob(f.embedding), int(f.embedding.shape[0]), engine.model_name,
                 round(f.det_score, 4), now))
        db.commit()
    except sqlite3.Error:
        safe_rollback(db)
        raise EnrollmentError("Database error - face data was not saved.")
    rec.invalidate_gallery()
    log_action(db, admin.get("id"), admin.get("username"), "face_enrolled", "student", student["student_code"],
               {"templates": len(good), "model": engine.model_name}, ip)
    return {"accepted": len(good), "rejected": len(per_image) - len(good), "per_image": per_image}


# ------------------------------------------------------------------- deletion
def delete_biometrics(db, student_id: int, admin: dict, ip: str = None) -> None:
    """Withdraw consent: wipe all embeddings. The person remains (manual attendance still possible)."""
    s = get_student(db, student_id)
    if s is None:
        raise EnrollmentError("Person not found.")
    try:
        db.execute("DELETE FROM face_embeddings WHERE student_id = ?", (student_id,))
        db.execute("UPDATE students SET consent_status='withdrawn', updated_at=? WHERE id=?", (now_utc_iso(), student_id))
        db.commit()
    except sqlite3.Error:
        safe_rollback(db)
        raise EnrollmentError("Database error - biometric data was not deleted.")
    rec.invalidate_gallery()
    log_action(db, admin.get("id"), admin.get("username"), "biometrics_deleted", "student", s["student_code"], {}, ip)


def delete_student(db, student_id: int, admin: dict, ip: str = None) -> None:
    """Remove the person, their embeddings and attendance records (ON DELETE CASCADE)."""
    s = get_student(db, student_id)
    if s is None:
        raise EnrollmentError("Person not found.")
    try:
        db.execute("DELETE FROM students WHERE id = ?", (student_id,))
        db.commit()
    except sqlite3.Error:
        safe_rollback(db)
        raise EnrollmentError("Database error - the person was not deleted.")
    rec.invalidate_gallery()
    log_action(db, admin.get("id"), admin.get("username"), "student_deleted", "student", s["student_code"], {}, ip)
