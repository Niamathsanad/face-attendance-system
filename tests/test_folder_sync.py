"""Drop-photos-in-a-folder enrollment."""
import cv2
import pytest

from conftest import make_image
from services import folder_sync_service as fs
from models.face_recognition_model import get_engine


def save(path, identity, noise=1, faces=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), make_image(identity, noise, faces))          # PNG keeps the fake-face pixels intact


def names(db):
    return {r["full_name"]: r["student_code"] for r in db.execute("SELECT full_name, student_code FROM students")}


def test_all_layouts_are_enrolled(db, tmp_path):
    save(tmp_path / "Murtaza.png", 11)
    save(tmp_path / "Ali (1).png", 12, 1); save(tmp_path / "Ali (2).png", 12, 2)
    save(tmp_path / "Sara" / "a.png", 13, 1); save(tmp_path / "Sara" / "b.png", 13, 2)
    save(tmp_path / "CS-9__Cara_Khan.png", 14)
    (tmp_path / "notes.txt").write_text("ignored")
    rep = fs.sync(db, tmp_path, engine=get_engine())
    assert rep["enrolled"] == 4 and rep["failed"] == 0
    n = names(db)
    assert set(n) == {"Murtaza", "Ali", "Sara", "Cara Khan"} and n["Cara Khan"] == "CS-9"
    assert db.execute("SELECT COUNT(*) FROM face_embeddings WHERE student_id=(SELECT id FROM students WHERE full_name='Ali')").fetchone()[0] == 2
    assert db.execute("SELECT consent_status FROM students WHERE full_name='Murtaza'").fetchone()[0] == "granted"


def test_second_run_skips_people_already_enrolled(db, tmp_path):
    save(tmp_path / "Murtaza.png", 11)
    assert fs.sync(db, tmp_path, engine=get_engine())["enrolled"] == 1
    rep = fs.sync(db, tmp_path, engine=get_engine())
    assert rep["enrolled"] == 0 and rep["skipped"] == 1
    assert db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 1
    assert fs.sync(db, tmp_path, engine=get_engine(), force=True)["enrolled"] == 1       # force re-enrolls


def test_withdrawn_consent_is_never_overridden(db, tmp_path):
    save(tmp_path / "Murtaza.png", 11)
    fs.sync(db, tmp_path, engine=get_engine())
    db.execute("DELETE FROM face_embeddings"); db.execute("UPDATE students SET consent_status='withdrawn'"); db.commit()
    rep = fs.sync(db, tmp_path, engine=get_engine())
    assert rep["skipped"] == 1 and db.execute("SELECT COUNT(*) FROM face_embeddings").fetchone()[0] == 0


def test_bad_photos_are_reported_and_leave_no_stub(db, tmp_path):
    save(tmp_path / "Ghost.png", 0)                                      # no face in the picture
    rep = fs.sync(db, tmp_path, engine=get_engine())
    assert rep["failed"] == 1 and "usable" in rep["results"][0]["message"]
    assert db.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0


def test_same_face_under_two_names_is_refused(db, tmp_path):
    save(tmp_path / "Ali.png", 11); save(tmp_path / "Twin.png", 11, 2)
    rep = fs.sync(db, tmp_path, engine=get_engine())
    assert rep["enrolled"] == 1 and rep["failed"] == 1


def test_empty_or_missing_folder_is_fine(db, tmp_path):
    assert fs.sync(db, tmp_path / "does_not_exist_yet", engine=get_engine())["results"] == []


def test_sync_button_route(auth_client, app, db, tmp_path):
    app.config["KNOWN_FACES_DIR"] = str(tmp_path)
    save(tmp_path / "Murtaza.png", 11)
    r = auth_client.post("/students/sync-folder", follow_redirects=True)
    assert b"1 enrolled" in r.data and b"Murtaza" in r.data
    assert b"Sync from known_faces folder" in auth_client.get("/students").data
    assert auth_client.post("/students/sync-folder").status_code == 302


def test_sync_route_requires_login(client):
    assert client.post("/students/sync-folder").status_code == 302
