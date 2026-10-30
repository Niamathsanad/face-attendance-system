"""
models/face_recognition_model.py - the ONLY file that talks to InsightFace.

Pretrained AI is used here (no training from scratch):
  1. DETECTION   : a pretrained face detector finds face boxes + 5 landmarks.
  2. ALIGNMENT   : InsightFace rotates/scales the face using the landmarks.
  3. EMBEDDING   : a pretrained recognition network turns the aligned face into
                   a vector of 512 numbers (the "embedding"). Pictures of the
                   same person give vectors that point in similar directions.
Everything else in this project (database, thresholds, attendance rules) is
ordinary application logic.

Because the rest of the program only sees `DetectedFace` objects, tests can
replace this engine with a fake one (see tests/conftest.py).
"""
from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass

import cv2
import numpy as np

warnings.filterwarnings("ignore", category=FutureWarning)   # harmless scikit-image notice from InsightFace


@dataclass
class DetectedFace:
    bbox: tuple[int, int, int, int]      # x1, y1, x2, y2 in the analysed image
    det_score: float                     # detector confidence 0..1
    embedding: np.ndarray                # L2-normalised float32 vector
    sharpness: float                     # variance of Laplacian (higher = sharper)

    @property
    def size(self) -> int:
        x1, y1, x2, y2 = self.bbox
        return int(min(x2 - x1, y2 - y1))


# ---------------------------------------------------------------- serialisation
def embedding_to_blob(vec: np.ndarray) -> bytes:
    """Serialisation format: little-endian float32, no header. 512 numbers = 2048 bytes."""
    return np.asarray(vec, dtype="<f4").tobytes()


def blob_to_embedding(blob: bytes, dim: int) -> np.ndarray:
    arr = np.frombuffer(blob, dtype="<f4")
    if arr.shape[0] != dim:
        raise ValueError(f"Embedding length {arr.shape[0]} does not match stored dimension {dim}")
    return arr.astype(np.float32, copy=True)


def l2_normalize(vec: np.ndarray) -> np.ndarray:
    vec = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


# -------------------------------------------------------------------- the engine
class FaceEngine:
    """Loads InsightFace lazily (first use) and analyses images."""

    def __init__(self, model_name: str = "buffalo_s", det_size: int = 640):
        self.model_name = model_name
        self.det_size = det_size
        self._app = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._app is not None:
            return
        with self._lock:
            if self._app is not None:
                return
            try:
                from insightface.app import FaceAnalysis
            except ImportError as exc:     # pragma: no cover
                raise RuntimeError("InsightFace is not installed. Run: pip install -r requirements.txt") from exc
            # allowed_modules skips gender/age and 3D landmarks -> faster on CPU.
            app = FaceAnalysis(name=self.model_name, providers=["CPUExecutionProvider"],
                               allowed_modules=["detection", "recognition"])
            app.prepare(ctx_id=-1, det_size=(self.det_size, self.det_size))
            self._app = app

    def warm_up(self) -> None:
        """Load the model now (downloads it on the very first run)."""
        self._ensure_loaded()

    @property
    def embedding_dim(self) -> int:
        return 512

    def analyze(self, bgr_image: np.ndarray) -> list[DetectedFace]:
        """Detect every face in a BGR image and return one DetectedFace per face."""
        self._ensure_loaded()
        with self._lock:
            faces = self._app.get(bgr_image)
        h, w = bgr_image.shape[:2]
        gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
        out: list[DetectedFace] = []
        for f in faces:
            x1, y1, x2, y2 = [int(round(v)) for v in f.bbox]
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            crop = cv2.resize(gray[y1:y2, x1:x2], (112, 112))
            sharp = float(cv2.Laplacian(crop, cv2.CV_64F).var())
            emb = getattr(f, "normed_embedding", None)
            if emb is None:
                continue
            out.append(DetectedFace((x1, y1, x2, y2), float(f.det_score),
                                    l2_normalize(emb), sharp))
        return out


# ------------------------------------------------------------ module-level singleton
_engine: FaceEngine | None = None


def get_engine() -> FaceEngine:
    global _engine
    if _engine is None:
        from config import Config
        _engine = FaceEngine(Config.FACE_MODEL_NAME, Config.DETECTION_SIZE)
    return _engine


def set_engine(engine) -> None:
    """Replace the engine (used by tests and by app.create_app)."""
    global _engine
    _engine = engine


def decode_image(data: bytes, max_side: int = 1280) -> np.ndarray | None:
    """Bytes (JPEG/PNG) -> BGR image, shrunk so the longest side <= max_side."""
    if not data:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img
