"""Database design: tables, constraints, cascades, serialisation, failure handling."""
import sqlite3

import numpy as np
import pytest

from conftest import ADMIN, enroll_fake, new_student
from models.face_recognition_model import blob_to_embedding, embedding_to_blob
from services import attendance_service as att
from services.time_utils import now_utc_iso


def test_all_tables_exist(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"administrators", "students", "face_embeddings", "attendance_sessions",
            "attendance_records", "audit_logs", "settings"} <= names


def test_default_admin_password_is_hashed(db):
    row = db.execute("SELECT password_hash FROM administrators WHERE username='admin'").fetchone()
    assert row["password_hash"] != "Admin@12345" and row["password_hash"].startswith("pbkdf2:")


def test_student_code_must_be_unique(db):
    new_student(db, "S001")
    with pytest.raises(Exception):
        new_student(db, "S001", name="Someone Else")


def test_foreign_keys_are_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO face_embeddings (student_id, embedding, embedding_dim, model_name, created_at) "
                   "VALUES (999, x'00', 1, 'm', 'now')")


def test_deleting_student_cascades_embeddings_and_attendance(db):
    sid = new_student(db); enroll_fake(db, sid, 5)
    sess = att.create_session(db, "Lec", None, None, ADMIN)
    att.mark_present(db, sess, sid)
    assert db.execute("SELECT COUNT(*) FROM face_embeddings").fetchone()[0] == 3
    db.execute("DELETE FROM students WHERE id=?", (sid,)); db.commit()
    assert db.execute("SELECT COUNT(*) FROM face_embeddings").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0] == 0


def test_database_allows_only_one_open_session(db):
    db.execute("INSERT INTO attendance_sessions (name, session_date, status, started_at) VALUES ('a','2026-01-01','open',?)", (now_utc_iso(),))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO attendance_sessions (name, session_date, status, started_at) VALUES ('b','2026-01-01','open',?)", (now_utc_iso(),))


def test_unique_constraint_blocks_duplicate_attendance(db):
    sid = new_student(db); sess = att.create_session(db, "Lec", None, None, ADMIN)
    db.execute("INSERT INTO attendance_records (session_id, student_id, status, source, marked_at) VALUES (?,?, 'Present','face',?)", (sess, sid, now_utc_iso()))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO attendance_records (session_id, student_id, status, source, marked_at) VALUES (?,?, 'Present','face',?)", (sess, sid, now_utc_iso()))


def test_embedding_serialisation_round_trip():
    v = np.random.default_rng(1).standard_normal(512).astype(np.float32)
    blob = embedding_to_blob(v)
    assert len(blob) == 512 * 4
    assert np.allclose(blob_to_embedding(blob, 512), v)
    with pytest.raises(ValueError):
        blob_to_embedding(blob, 256)          # wrong stored dimension is rejected


def test_embedding_is_stored_as_blob_not_text(db):
    sid = new_student(db); enroll_fake(db, sid, 5, n=1)
    row = db.execute("SELECT typeof(embedding) t, length(embedding) n FROM face_embeddings").fetchone()
    assert row["t"] == "blob" and row["n"] == 2048


def test_database_failure_is_reported_safely(db):
    sid = new_student(db); sess = att.create_session(db, "Lec", None, None, ADMIN)
    db.close()                                # simulate a broken connection
    with pytest.raises(att.AttendanceError):
        att.mark_present(db, sess, sid)
