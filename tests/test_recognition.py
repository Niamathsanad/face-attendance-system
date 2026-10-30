"""Matching maths, thresholds, confirmation tracker, and (optional) real-model / webcam tests."""
import os
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from conftest import ADMIN, new_student
from models import face_recognition_model as frm
from services import enrollment_service as es
from services import recognition_service as rec

SAMPLES = Path(__file__).resolve().parent.parent / "sample_images"


def unit(*v):
    return np.asarray(v, dtype=np.float32) / np.linalg.norm(v)


def gallery_of(*people):
    """people = list of (name, [embeddings])"""
    rows, idx, info = [], [], []
    for i, (name, embs) in enumerate(people):
        info.append({"id": i + 1, "code": name, "name": name, "department": "d", "class_name": "c"})
        for e in embs:
            rows.append(e); idx.append(i)
    return rec.Gallery(np.vstack(rows), np.asarray(idx), info)


def test_match_above_threshold():
    g = gallery_of(("ali", [unit(1, 0, 0)]), ("bob", [unit(0, 1, 0)]))
    m = rec.match_embedding(unit(0.95, 0.05, 0), g, 0.4, 0.05)
    assert m.reason == "match" and m.person["name"] == "ali" and m.score > 0.99


def test_reject_below_threshold():
    g = gallery_of(("ali", [unit(1, 0, 0)]))
    m = rec.match_embedding(unit(0, 1, 0), g, 0.4)
    assert m.person is None and m.reason == "below_threshold"


def test_threshold_is_configurable():
    g = gallery_of(("ali", [unit(1, 0, 0)]))
    probe = unit(1, 1, 0)                                  # cosine similarity = 0.707
    assert rec.match_embedding(probe, g, 0.6).person is not None
    assert rec.match_embedding(probe, g, 0.8).person is None


def test_ambiguous_between_two_people_is_rejected():
    g = gallery_of(("ali", [unit(1, 0.1, 0)]), ("bob", [unit(1, -0.1, 0)]))
    m = rec.match_embedding(unit(1, 0, 0), g, 0.4, 0.05)
    assert m.person is None and m.reason == "ambiguous"


def test_best_template_of_a_person_counts():
    g = gallery_of(("ali", [unit(0, 0, 1), unit(1, 0, 0)]), ("bob", [unit(0, 1, 0)]))
    assert rec.match_embedding(unit(1, 0.01, 0), g, 0.4, 0.05).person["name"] == "ali"


def test_empty_gallery_matches_nobody():
    empty = rec.Gallery(np.zeros((0, 3), dtype=np.float32), np.zeros(0, dtype=np.int32), [])
    assert rec.match_embedding(unit(1, 0, 0), empty, 0.4).reason == "empty_gallery"


def test_confirmation_tracker_requires_consecutive_hits():
    t = rec.ConfirmationTracker(window_seconds=4)
    assert t.hit(1, 3, now=100) == (False, 1) and t.hit(1, 3, now=101) == (False, 2) and t.hit(1, 3, now=102) == (True, 3)
    assert t.hit(2, 2, now=100) == (False, 1)
    assert t.hit(2, 2, now=110) == (False, 1)              # too slow -> counter restarts


# ------------------------------------------------ real model (marked `model`)
@pytest.fixture
def real_engine():
    try:
        engine = frm.FaceEngine("buffalo_s", 640)
        engine.warm_up()
    except Exception as exc:                               # no internet / model not downloadable
        pytest.skip(f"Real face model unavailable: {exc}")
    frm.set_engine(engine)
    rec.invalidate_gallery()
    yield engine


def load(name):
    return frm.decode_image((SAMPLES / name).read_bytes())


@pytest.mark.model
def test_real_model_recognises_known_and_rejects_unknown(db, real_engine):
    sid = new_student(db, "R1", "Altamash")
    rep = es.enroll_images(db, sid, [load(f"Altamash ({i}).jpeg") for i in (1, 2, 3)], ADMIN, min_images=3)
    assert rep["accepted"] == 3
    gallery = rec.load_gallery(db, real_engine.model_name)
    # known person: a photo that was NOT used for enrollment
    face = real_engine.analyze(load("Altamash (4).jpeg"))[0]
    known = rec.match_embedding(face.embedding, gallery, 0.40, 0.05)
    assert known.person is not None and known.person["code"] == "R1"
    # unknown person
    stranger = real_engine.analyze(load("Murtaza.jpeg"))[0]
    unknown = rec.match_embedding(stranger.embedding, gallery, 0.40, 0.05)
    assert unknown.person is None
    print(f"\n  same-person score={known.score:.3f}  different-person score={unknown.score:.3f}")


@pytest.mark.model
def test_real_model_rejects_blurry_and_tiny_faces(db, real_engine):
    sid = new_student(db, "R2", "Blur Test")
    sharp = load("Murtaza.jpeg")
    blurry = cv2.GaussianBlur(sharp, (0, 0), 12)
    tiny = cv2.resize(sharp, (160, 120))
    with pytest.raises(es.EnrollmentError):
        es.enroll_images(db, sid, [blurry, tiny], ADMIN, min_images=1)


@pytest.mark.model
def test_real_model_latency_is_reasonable(real_engine):
    img = cv2.resize(load("Altamash (1).jpeg"), (640, 480))
    real_engine.analyze(img)                               # warm-up
    t = time.perf_counter()
    for _ in range(5):
        real_engine.analyze(img)
    avg_ms = (time.perf_counter() - t) / 5 * 1000
    print(f"\n  average analysis time on this machine: {avg_ms:.0f} ms per 640x480 frame")
    assert avg_ms < 3000                                   # generous bound; real figures depend on your CPU


# ------------------------------------------------ real webcam (marked `webcam`)
@pytest.mark.webcam
@pytest.mark.skipif(os.environ.get("RUN_WEBCAM_TESTS") != "1", reason="set RUN_WEBCAM_TESTS=1 to test a physical webcam")
def test_webcam_returns_a_frame():
    cap = cv2.VideoCapture(0)
    try:
        ok, frame = cap.read()
        assert ok and frame is not None and frame.size > 0
    finally:
        cap.release()
