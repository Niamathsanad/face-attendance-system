"""Sessions, duplicate prevention, recognition->attendance rules, corrections, filters, calculations."""
from datetime import timedelta

import pytest

from conftest import ADMIN, enroll_fake, make_image, new_student, png_data_url
from services import attendance_service as att
from services import recognition_service as rec
from services import reporting_service as rs
from services import time_utils as tu
from services.settings_service import set_setting
from services.time_utils import now_utc_iso
from services.validators import ValidationError
from models.face_recognition_model import get_engine


def count(db, table="attendance_records"):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def frame(db, identity, noise=1, faces=1):
    sess = att.get_open_session(db)
    return rec.process_frame(db, make_image(identity, noise, faces), sess, engine=get_engine())


# ------------------------------------------------------------------ sessions
def test_create_and_close_session(db):
    sid = att.create_session(db, "Lecture 1", "CS", "Sem-5", ADMIN)
    s = att.get_open_session(db)
    assert s["id"] == sid and s["session_date"] == tu.local_today_str() and s["department"] == "CS"
    att.close_session(db, sid, ADMIN)
    assert att.get_open_session(db) is None
    with pytest.raises(att.AttendanceError):
        att.close_session(db, sid, ADMIN)               # cannot close twice


def test_only_one_open_session_at_a_time(db):
    att.create_session(db, "AA", None, None, ADMIN)
    with pytest.raises(att.AttendanceError):
        att.create_session(db, "BB", None, None, ADMIN)


def test_session_name_validation(db):
    with pytest.raises(ValidationError):
        att.create_session(db, "", None, None, ADMIN)


def test_session_routes(auth_client, db):
    r = auth_client.post("/sessions/create", data={"name": "Lab 1"})
    assert r.status_code == 302 and att.get_open_session(db)["name"] == "Lab 1"
    r = auth_client.post("/sessions/create", data={"name": "Lab 2"}, follow_redirects=True)
    assert b"already open" in r.data
    sid = att.get_open_session(db)["id"]
    auth_client.post(f"/sessions/{sid}/close")
    assert att.get_open_session(db) is None


# ------------------------------------------------------ duplicate prevention
def test_duplicate_attendance_prevented_by_database(db):
    sid = new_student(db); sess = att.create_session(db, "Lec", None, None, ADMIN)
    assert att.mark_present(db, sess, sid) == "marked"
    assert att.mark_present(db, sess, sid) == "already"
    assert att.mark_present(db, sess, sid) == "already"
    assert count(db) == 1


def test_same_person_can_attend_two_different_sessions(db):
    sid = new_student(db)
    s1 = att.create_session(db, "Lec-1", None, None, ADMIN); att.close_session(db, s1, ADMIN)
    s2 = att.create_session(db, "Lec-2", None, None, ADMIN)
    assert att.mark_present(db, s1, sid) == "marked" and att.mark_present(db, s2, sid) == "marked"


# ------------------------------------------- recognition -> attendance rules
def test_known_person_is_marked_after_confirmation_frames(db):
    sid = new_student(db); enroll_fake(db, sid, 11)
    att.create_session(db, "Lec", None, None, ADMIN)
    r1 = frame(db, 11, 4)["faces"][0]
    assert r1["status"] == "verifying" and count(db) == 0            # one frame is not enough
    r2 = frame(db, 11, 5)["faces"][0]
    assert r2["status"] == "marked" and r2["student_code"] == "S001" and count(db) == 1
    assert frame(db, 11, 6)["faces"][0]["status"] == "already" and count(db) == 1


def test_unknown_person_never_gets_attendance(db):
    sid = new_student(db); enroll_fake(db, sid, 11)
    att.create_session(db, "Lec", None, None, ADMIN)
    for n in range(6):
        f = frame(db, 77, n)["faces"][0]
        assert f["status"] == "unknown" and f["label"] == "Unknown Person" and f["student_code"] is None
    assert count(db) == 0


def test_unknown_person_with_empty_gallery(db):
    att.create_session(db, "Lec", None, None, ADMIN)
    assert frame(db, 5)["faces"][0]["status"] == "unknown" and count(db) == 0


def test_no_open_session_means_nothing_recorded(db):
    sid = new_student(db); enroll_fake(db, sid, 11)
    for n in range(4):
        assert frame(db, 11, n)["faces"][0]["status"] == "no_session"
    assert count(db) == 0


def test_session_scope_limits_who_can_be_marked(db):
    a = new_student(db, "A1", "Ali", "CS", "Sem-5"); b = new_student(db, "B1", "Bilal", "EE", "Sem-3")
    enroll_fake(db, a, 11); enroll_fake(db, b, 22)
    att.create_session(db, "CS lecture", "CS", None, ADMIN)
    frame(db, 22, 1)
    assert frame(db, 22, 2)["faces"][0]["status"] == "out_of_scope"
    assert count(db) == 0


def test_several_faces_in_one_frame(db):
    a = new_student(db, "A1", "Ali"); b = new_student(db, "B1", "Bilal")
    enroll_fake(db, a, 11); enroll_fake(db, b, 111)                  # fake 2nd face = identity + 100
    att.create_session(db, "Lec", None, None, ADMIN)
    frame(db, 11, 4, faces=2)
    res = frame(db, 11, 5, faces=2)
    assert sorted(f["status"] for f in res["faces"]) == ["marked", "marked"] and count(db) == 2


def test_confirmation_setting_is_respected(db):
    sid = new_student(db); enroll_fake(db, sid, 11)
    set_setting(db, "confirmations_required", 1); db.commit()
    att.create_session(db, "Lec", None, None, ADMIN)
    assert frame(db, 11, 4)["faces"][0]["status"] == "marked"


def test_database_error_during_marking_is_handled(db, monkeypatch):
    sid = new_student(db); enroll_fake(db, sid, 11)
    set_setting(db, "confirmations_required", 1); db.commit()
    att.create_session(db, "Lec", None, None, ADMIN)

    def boom(*a, **k):
        raise att.AttendanceError("Database error - attendance was not saved. Please try again.")
    monkeypatch.setattr(att, "mark_present", boom)
    f = frame(db, 11, 4)["faces"][0]
    assert f["status"] == "error" and "not saved" in f["message"] and count(db) == 0


def test_recognize_api_end_to_end(auth_client, db):
    sid = new_student(db); enroll_fake(db, sid, 11)
    auth_client.post("/sessions/create", data={"name": "API lecture"})
    last = None
    for n in (1, 2, 3):
        last = auth_client.post("/api/recognize", json={"image": png_data_url(make_image(11, n))}).get_json()
    assert last["ok"] and last["session"]["name"] == "API lecture"
    assert count(db) == 1
    bad = auth_client.post("/api/recognize", json={"image": "not-an-image"})
    assert bad.status_code == 400


# ----------------------------------------------------------------- corrections
def test_correction_flow_with_audit_trail(db):
    sid = new_student(db); sess = att.create_session(db, "Lec", None, None, ADMIN)
    att.mark_present(db, sess, sid, 0.8, "face")
    att.correct_record(db, sess, sid, "Absent", "Camera misidentified a visitor", ADMIN)
    row = db.execute("SELECT * FROM attendance_records").fetchone()
    assert row["status"] == "Absent" and row["is_corrected"] == 1 and row["original_status"] == "Present"
    log = db.execute("SELECT * FROM audit_logs WHERE action='attendance_corrected'").fetchone()
    assert "Camera misidentified" in log["details"]
    df = att.attendance_matrix(db)
    assert df.iloc[0]["record_type"] == "Manual correction"


def test_manual_present_for_student_without_record(db):
    sid = new_student(db); sess = att.create_session(db, "Lec", None, None, ADMIN)
    att.correct_record(db, sess, sid, "Present", "Camera not available", ADMIN)
    r = db.execute("SELECT * FROM attendance_records").fetchone()
    assert r["source"] == "manual" and r["status"] == "Present" and r["original_status"] is None
    assert att.attendance_matrix(db).iloc[0]["record_type"] == "Manual correction"


def test_correction_requires_reason_and_a_real_change(db):
    sid = new_student(db); sess = att.create_session(db, "Lec", None, None, ADMIN)
    with pytest.raises(ValidationError):
        att.correct_record(db, sess, sid, "Present", "", ADMIN)
    with pytest.raises(ValidationError):
        att.correct_record(db, sess, sid, "Absent", "no change needed", ADMIN)      # already absent
    with pytest.raises(ValidationError):
        att.correct_record(db, sess, sid, "Late", "bad status", ADMIN)


def test_camera_record_is_distinguished_from_correction(db):
    a = new_student(db, "A1", "Ali"); b = new_student(db, "B1", "Bilal")
    sess = att.create_session(db, "Lec", None, None, ADMIN)
    att.mark_present(db, sess, a, 0.7, "face"); att.correct_record(db, sess, b, "Present", "teacher confirmed", ADMIN)
    types = dict(zip(att.attendance_matrix(db)["student_code"], att.attendance_matrix(db)["record_type"]))
    assert types == {"A1": "Recorded by camera", "B1": "Manual correction"}


def test_correct_route(auth_client, db):
    sid = new_student(db); sess = att.create_session(db, "Lec", None, None, ADMIN)
    r = auth_client.post("/attendance/correct", data={"session_id": sess, "student_id": sid, "status": "Present", "reason": "manual check"})
    assert r.status_code == 302 and count(db) == 1


# ------------------------------------------------- filters and calculations
def _make_session(db, name, day, dept=None, cls=None):
    cur = db.execute("INSERT INTO attendance_sessions (name, session_date, department, class_name, status, started_at, ended_at) "
                     "VALUES (?,?,?,?, 'closed', ?, ?)", (name, day, dept, cls, now_utc_iso(), now_utc_iso()))
    db.commit(); return cur.lastrowid


def _present(db, sess, sid):
    db.execute("INSERT INTO attendance_records (session_id, student_id, status, source, marked_at) VALUES (?,?, 'Present','face',?)", (sess, sid, now_utc_iso()))
    db.commit()


def test_date_filter_and_absent_calculation(db):
    a, b = new_student(db, "A1", "Ali"), new_student(db, "B1", "Bilal")
    db.execute("UPDATE students SET registration_date='2026-01-01'"); db.commit()
    s1, s2 = _make_session(db, "d1", "2026-02-01"), _make_session(db, "d2", "2026-02-02")
    _present(db, s1, a); _present(db, s1, b); _present(db, s2, a)
    day1 = att.attendance_matrix(db, "2026-02-01", "2026-02-01")
    assert att.summarize(day1) == {"expected": 2, "present": 2, "absent": 0, "percentage": 100.0}
    day2 = att.attendance_matrix(db, "2026-02-02", "2026-02-02")
    assert att.summarize(day2)["absent"] == 1 and list(day2[day2.status == "Absent"]["student_code"]) == ["B1"]
    both = att.attendance_matrix(db, "2026-02-01", "2026-02-02")
    pct = att.student_percentages(both).set_index("student_code")["percentage"].to_dict()
    assert pct == {"A1": 100.0, "B1": 50.0}
    assert att.attendance_matrix(db, "2026-03-01", "2026-03-05").empty
    assert len(att.attendance_matrix(db, "2026-02-01", "2026-02-02", status="Absent")) == 1


def test_department_and_class_filters_and_search(db):
    new_student(db, "A1", "Ali", "CS", "Sem-5"); new_student(db, "B1", "Bilal", "EE", "Sem-3")
    db.execute("UPDATE students SET registration_date='2026-01-01'"); db.commit()
    _make_session(db, "d1", "2026-02-01")
    assert list(att.attendance_matrix(db, department="EE")["student_code"]) == ["B1"]
    assert list(att.attendance_matrix(db, class_name="Sem-5")["student_code"]) == ["A1"]
    assert list(att.attendance_matrix(db, search="Bil")["student_code"]) == ["B1"]
    assert list(att.attendance_matrix(db, search="A1")["student_code"]) == ["A1"]


def test_person_registered_after_session_is_not_counted_absent(db):
    a = new_student(db, "A1", "Ali"); db.execute("UPDATE students SET registration_date='2026-02-10'"); db.commit()
    _make_session(db, "old", "2026-02-01")
    assert att.attendance_matrix(db).empty


def test_session_with_scope_only_expects_matching_people(db):
    new_student(db, "A1", "Ali", "CS", "Sem-5"); new_student(db, "B1", "Bilal", "EE", "Sem-3")
    db.execute("UPDATE students SET registration_date='2026-01-01'"); db.commit()
    _make_session(db, "cs only", "2026-02-01", dept="CS")
    assert list(att.attendance_matrix(db)["student_code"]) == ["A1"]


def test_attendance_page_filters_via_http(auth_client, db):
    new_student(db, "A1", "Ali"); db.execute("UPDATE students SET registration_date='2026-01-01'"); db.commit()
    _make_session(db, "Feb lecture", "2026-02-01")
    assert b"Feb lecture" in auth_client.get("/attendance?date_from=2026-02-01&date_to=2026-02-01").data
    assert b"Feb lecture" not in auth_client.get("/attendance?date_from=2026-03-01&date_to=2026-03-01").data
    assert auth_client.get("/attendance?date_from=garbage").status_code == 200       # invalid dates fall back safely


def test_dashboard_numbers_come_from_the_database(auth_client, db):
    a, b, c = new_student(db, "A1", "Ali"), new_student(db, "B1", "Bilal"), new_student(db, "C1", "Cara")
    sess = att.create_session(db, "Today", None, None, ADMIN)
    att.mark_present(db, sess, a); att.mark_present(db, sess, b)
    d = auth_client.get("/api/dashboard").get_json()
    s = d["stats"]
    assert (s["total_registered"], s["present_today"], s["absent_today"], s["percentage_today"]) == (3, 2, 1, 66.7)
    assert len(d["recent"]) == 2 and d["daily"]["present"][-1] == 2 and d["weekly"]["present"][-1] == 2
    assert d["monthly"]["present"][-1] == 2


def test_dashboard_with_no_data_is_empty_not_fake(auth_client):
    d = auth_client.get("/api/dashboard").get_json()
    assert d["stats"]["total_registered"] == 0 and d["stats"]["percentage_today"] is None and d["recent"] == []
    assert sum(d["daily"]["present"]) == 0
