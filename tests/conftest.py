"""
conftest.py - shared fixtures.

NO WEBCAM / NO MODEL NEEDED for most tests: a FakeEngine turns small synthetic
images into deterministic "face embeddings". Image encoding (see make_image):
    pixel[0,0] = identity (0 = no face, otherwise the person)
    pixel[0,1] = noise id (different photos of the same person)
    pixel[0,2] = number of faces (1 or 2; the 2nd face is identity+100)
Tests marked `model` use the real InsightFace model and the photos in sample_images/.
"""
import base64
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app                                   # noqa: E402
from database import db as database                          # noqa: E402
from models import face_recognition_model as frm             # noqa: E402
from models.face_recognition_model import DetectedFace, l2_normalize  # noqa: E402
from services import enrollment_service as es                # noqa: E402
from services import recognition_service as rec              # noqa: E402
from services import security                                # noqa: E402

ADMIN = {"id": None, "username": "tester"}


def _emb(identity: int, noise: int) -> np.ndarray:
    base = np.random.default_rng(identity).standard_normal(512)
    jitter = np.random.default_rng(10_000 + noise).standard_normal(512) * 0.15
    return l2_normalize(base + jitter)


class FakeEngine:
    model_name = "fake-model"
    embedding_dim = 512

    def analyze(self, img):
        ident, noise, count = int(img[0, 0, 0]), int(img[0, 1, 0]), max(1, int(img[0, 2, 0]))
        if ident == 0:
            return []
        faces = [DetectedFace((20, 20, 140, 140), 0.95, _emb(ident, noise), 120.0)]
        if count >= 2:
            faces.append(DetectedFace((170, 20, 290, 140), 0.93, _emb(ident + 100, noise), 120.0))
        return faces

    def warm_up(self):
        pass


def make_image(identity: int, noise: int = 0, faces: int = 1) -> np.ndarray:
    img = np.full((240, 320, 3), 128, dtype=np.uint8)
    img[0, 0, 0], img[0, 1, 0], img[0, 2, 0] = identity, noise, faces
    return img


def png_data_url(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)           # PNG is lossless, so the encoded pixels survive
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


@pytest.fixture
def app(tmp_path):
    application = create_app({
        "DATABASE": str(tmp_path / "test.db"), "TESTING": True, "CSRF_ENABLED": False,
        "SKIP_MODEL_WARMUP": True, "PASSWORD_HASH_METHOD": "pbkdf2:sha256:1000",
        "DEFAULT_ADMIN_PASSWORD": "Admin@12345",
    })
    frm.set_engine(FakeEngine())
    rec.invalidate_gallery(); rec.tracker.reset(); security.reset_throttle()
    yield application
    rec.invalidate_gallery()


@pytest.fixture
def csrf_app(tmp_path):
    application = create_app({
        "DATABASE": str(tmp_path / "csrf.db"), "TESTING": True, "CSRF_ENABLED": True, "SKIP_MODEL_WARMUP": True,
        "PASSWORD_HASH_METHOD": "pbkdf2:sha256:1000"})
    frm.set_engine(FakeEngine()); security.reset_throttle()
    return application


@pytest.fixture
def db(app):
    conn = database.connect(app.config["DATABASE"])
    yield conn
    conn.close()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="admin", password="Admin@12345", **kw):
    return client.post("/login", data={"username": username, "password": password}, **kw)


@pytest.fixture
def auth_client(app, client, db):
    """A client that is logged in (default password-change requirement switched off)."""
    db.execute("UPDATE administrators SET must_change_password = 0"); db.commit()
    assert login(client).status_code == 302
    return client


def new_student(db, code="S001", name="Ali Khan", dept="CS", cls="Sem-5") -> int:
    return es.create_student(db, {"student_code": code, "full_name": name, "department": dept,
                                  "class_name": cls, "email": ""}, ADMIN)


def enroll_fake(db, student_id: int, identity: int, n: int = 3) -> dict:
    imgs = [make_image(identity, noise=i) for i in range(1, n + 1)]
    return es.enroll_images(db, student_id, imgs, ADMIN, min_images=1)


def extract_csrf(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
