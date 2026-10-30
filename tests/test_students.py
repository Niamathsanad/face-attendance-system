"""Registration, duplicate IDs, enrollment, consent, deletion of biometric data."""
import pytest

from conftest import ADMIN, enroll_fake, make_image, new_student, png_data_url
from services import enrollment_service as es
from services import recognition_service as rec

FORM = {"student_code": "S100", "full_name": "Sara Ahmed", "department": "CS", "class_name": "Sem-5",
        "email": "sara@example.com", "consent": "on"}


def test_register_student_success(auth_client, db):
    r = auth_client.post("/students/register", data=FORM)
    assert r.status_code == 302 and "/enroll" in r.headers["Location"]
    row = db.execute("SELECT * FROM students WHERE student_code='S100'").fetchone()
    assert row["consent_status"] == "granted" and row["registration_date"]


def test_duplicate_student_id_rejected(auth_client, db):
    auth_client.post("/students/register", data=FORM)
    r = auth_client.post("/students/register", data={**FORM, "full_name": "Other"}, follow_redirects=True)
    assert b"already registered" in r.data
    assert db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 1


@pytest.mark.parametrize("change,msg", [({"consent": ""}, b"consent"), ({"student_code": "bad id!"}, b"ID must be"),
                                        ({"email": "not-an-email"}, b"Email"), ({"full_name": ""}, b"Full name")])
def test_registration_validation(auth_client, db, change, msg):
    data = {**FORM, **change}
    if change.get("consent") == "":
        data.pop("consent")
    r = auth_client.post("/students/register", data=data)
    assert r.status_code == 200 and msg.lower() in r.data.lower()
    assert db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0


def test_html_is_escaped_in_student_list(auth_client, db):
    new_student(db, "X1", name="<script>alert(1)</script>")
    html = auth_client.get("/students").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_sql_injection_text_is_just_text(auth_client, db):
    new_student(db, "S1", name="Ali")
    r = auth_client.get("/students?q=' OR 1=1 --")
    assert r.status_code == 200 and b"Ali" not in r.data


def test_search_by_id_and_name(auth_client, db):
    new_student(db, "S1", name="Ali Khan"); new_student(db, "S2", name="Sara Ahmed")
    assert b"Sara Ahmed" in auth_client.get("/students?q=S2").data
    assert b"Ali Khan" not in auth_client.get("/students?q=Sara").data


def test_enrollment_via_api_stores_templates_only(auth_client, db):
    sid = new_student(db)
    imgs = [png_data_url(make_image(7, noise=i)) for i in (1, 2, 3)]
    r = auth_client.post(f"/api/students/{sid}/enroll", json={"images": imgs})
    j = r.get_json()
    assert r.status_code == 200 and j["ok"] and j["accepted"] == 3
    assert db.execute("SELECT COUNT(*) FROM face_embeddings WHERE student_id=?", (sid,)).fetchone()[0] == 3


def test_enrollment_needs_minimum_images(auth_client, db):
    sid = new_student(db)
    r = auth_client.post(f"/api/students/{sid}/enroll", json={"images": [png_data_url(make_image(7, 1))]})
    assert r.status_code == 400 and "at least 3" in r.get_json()["error"]


def test_enrollment_rejects_no_face_and_multiple_faces(db):
    sid = new_student(db)
    imgs = [make_image(0), make_image(7, 1, faces=2), make_image(7, 2), make_image(7, 3), make_image(7, 4)]
    rep = es.enroll_images(db, sid, imgs, ADMIN, min_images=3)
    reasons = {p["index"]: p["reason"] for p in rep["per_image"]}
    assert "no face" in reasons[0] and "more than one" in reasons[1] and rep["accepted"] == 3


def test_enrollment_rejects_unreadable_image(db):
    sid = new_student(db)
    rep = es.enroll_images(db, sid, [None, make_image(7, 1)], ADMIN, min_images=1)
    assert rep["accepted"] == 1 and rep["per_image"][0]["ok"] is False


def test_enrollment_rejects_images_of_different_people(db):
    sid = new_student(db)
    with pytest.raises(es.EnrollmentError):
        es.enroll_images(db, sid, [make_image(7, 1), make_image(7, 2), make_image(55, 3)], ADMIN, min_images=3)


def test_same_face_cannot_be_enrolled_under_two_ids(db):
    a, b = new_student(db, "A1", "Ali"), new_student(db, "B1", "Bilal")
    enroll_fake(db, a, 9)
    with pytest.raises(es.EnrollmentError) as exc:
        enroll_fake(db, b, 9)
    assert "already matches" in str(exc.value)


def test_enrollment_refused_without_consent(db):
    sid = new_student(db)
    db.execute("UPDATE students SET consent_status='withdrawn'"); db.commit()
    with pytest.raises(es.EnrollmentError):
        enroll_fake(db, sid, 3)


def test_reenrollment_replaces_old_templates(db):
    sid = new_student(db); enroll_fake(db, sid, 4, n=3); enroll_fake(db, sid, 4, n=2)
    assert db.execute("SELECT COUNT(*) FROM face_embeddings WHERE student_id=?", (sid,)).fetchone()[0] == 2


def test_delete_biometrics_removes_all_templates(auth_client, db):
    sid = new_student(db); enroll_fake(db, sid, 4)
    r = auth_client.post(f"/students/{sid}/delete-biometrics")
    assert r.status_code == 302
    assert db.execute("SELECT COUNT(*) FROM face_embeddings").fetchone()[0] == 0
    assert db.execute("SELECT consent_status FROM students WHERE id=?", (sid,)).fetchone()[0] == "withdrawn"
    assert rec.load_gallery(db, "fake-model").empty                    # recognition cache refreshed too
    assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='biometrics_deleted'").fetchone()[0] == 1


def test_delete_student_removes_everything(auth_client, db):
    sid = new_student(db); enroll_fake(db, sid, 4)
    assert auth_client.post(f"/students/{sid}/delete").status_code == 302
    for t in ("students", "face_embeddings", "attendance_records"):
        assert db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
