"""
services/recognition_service.py - turns a camera frame into identity decisions.

Pipeline for every frame:
  detect faces -> embedding (pretrained AI, in models/)
  -> cosine similarity against every enrolled embedding   (maths)
  -> threshold + margin decision                           (application logic)
  -> confirmation over several frames                      (application logic)
  -> attendance rules + database insert                    (application logic)

Key ideas
  * Embeddings are L2-normalised, so cosine similarity = a simple dot product.
    1.0 = identical direction, ~0 = unrelated faces.
  * A person is recognised only if best_score >= threshold AND the best person
    beats the second-best person by `min_margin` (avoids look-alike confusion).
  * A person must be matched in N consecutive frames before attendance is saved
    (one lucky frame is not enough).
  * Unknown people NEVER get an attendance record.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass

import numpy as np

from models.face_recognition_model import blob_to_embedding, get_engine
from services import attendance_service as att
from services.settings_service import get_setting


# --------------------------------------------------------------------- gallery
@dataclass
class Gallery:
    matrix: np.ndarray            # (N, D) every enrolled embedding
    person_index: np.ndarray      # (N,) which person (index into `people`) each row belongs to
    people: list[dict]            # id, code, name, department, class_name

    @property
    def empty(self) -> bool:
        return self.matrix.shape[0] == 0


_gallery_cache: dict = {}
_gallery_lock = threading.Lock()


def invalidate_gallery() -> None:
    """Call after enrollment / deletion so the next frame sees fresh data."""
    with _gallery_lock:
        _gallery_cache.clear()


def _db_key(db: sqlite3.Connection) -> str:
    row = db.execute("PRAGMA database_list").fetchone()
    return str(row[2]) if row else ":memory:"


def load_gallery(db: sqlite3.Connection, model_name: str) -> Gallery:
    key = (_db_key(db), model_name)
    with _gallery_lock:
        cached = _gallery_cache.get(key)
        if cached is not None:
            return cached
    rows = db.execute(
        "SELECT e.embedding, e.embedding_dim, s.id, s.student_code, s.full_name, s.department, s.class_name "
        "FROM face_embeddings e JOIN students s ON s.id = e.student_id "
        "WHERE e.model_name = ? AND s.consent_status = 'granted' ORDER BY s.id, e.id", (model_name,)
    ).fetchall()
    vectors, idx, people, pos = [], [], [], {}
    for r in rows:
        try:
            vec = blob_to_embedding(r["embedding"], r["embedding_dim"])
        except ValueError:
            continue                                    # skip a corrupted template safely
        if r["id"] not in pos:
            pos[r["id"]] = len(people)
            people.append({"id": r["id"], "code": r["student_code"], "name": r["full_name"],
                           "department": r["department"], "class_name": r["class_name"]})
        vectors.append(vec)
        idx.append(pos[r["id"]])
    matrix = np.vstack(vectors).astype(np.float32) if vectors else np.zeros((0, 512), dtype=np.float32)
    gallery = Gallery(matrix, np.asarray(idx, dtype=np.int32), people)
    with _gallery_lock:
        _gallery_cache[key] = gallery
    return gallery


# -------------------------------------------------------------------- matching
@dataclass
class MatchResult:
    person: dict | None       # the matched person, or None
    score: float              # best cosine similarity found (even if rejected)
    second: float             # best score of a DIFFERENT person
    reason: str               # 'match' | 'below_threshold' | 'ambiguous' | 'empty_gallery'


def match_embedding(embedding: np.ndarray, gallery: Gallery, threshold: float,
                    min_margin: float = 0.0) -> MatchResult:
    if gallery.empty:
        return MatchResult(None, 0.0, 0.0, "empty_gallery")
    sims = gallery.matrix @ np.asarray(embedding, dtype=np.float32)        # cosine similarities
    best = np.full(len(gallery.people), -1.0, dtype=np.float32)
    np.maximum.at(best, gallery.person_index, sims)                        # best score per person
    order = np.argsort(best)[::-1]
    top = float(best[order[0]])
    second = float(best[order[1]]) if len(order) > 1 else -1.0
    if top < threshold:
        return MatchResult(None, top, second, "below_threshold")
    if len(order) > 1 and (top - second) < min_margin:
        return MatchResult(None, top, second, "ambiguous")
    return MatchResult(gallery.people[int(order[0])], top, second, "match")


# ------------------------------------------------------------- confirmation
class ConfirmationTracker:
    """Counts consecutive recognitions of the same person."""

    def __init__(self, window_seconds: float = 4.0):
        self.window = window_seconds
        self._hits: dict[int, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, student_id: int, required: int, now: float | None = None) -> tuple[bool, int]:
        now = time.time() if now is None else now
        with self._lock:
            count, last = self._hits.get(student_id, (0, 0.0))
            count = count + 1 if (now - last) <= self.window else 1
            self._hits[student_id] = (count, now)
            confirmed = count >= required
            if confirmed:
                self._hits.pop(student_id, None)
            return confirmed, count

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


tracker = ConfirmationTracker()


# ------------------------------------------------------------------ the pipeline
def process_frame(db: sqlite3.Connection, frame_bgr: np.ndarray, session: sqlite3.Row | None,
                  engine=None, mark: bool = True, max_faces: int = 10) -> dict:
    """Analyse one frame. Returns a JSON-friendly dict for the browser / desktop window."""
    engine = engine or get_engine()
    threshold = float(get_setting(db, "similarity_threshold"))
    margin = float(get_setting(db, "min_margin"))
    required = int(get_setting(db, "confirmations_required"))
    gallery = load_gallery(db, engine.model_name)

    faces = engine.analyze(frame_bgr)
    faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
    faces = faces[:max_faces]

    results, claimed = [], {}
    for face in faces:
        x1, y1, x2, y2 = face.bbox
        item = {"bbox": [x1, y1, x2, y2], "label": "Unknown Person", "status": "unknown",
                "student_code": None, "score": None, "message": "No reliable match - attendance NOT recorded."}
        m = match_embedding(face.embedding, gallery, threshold, margin)
        item["score"] = round(m.score, 3) if m.reason != "empty_gallery" else None
        if m.person is None:
            if m.reason == "ambiguous":
                item["message"] = "Ambiguous match between two people - treated as unknown."
            results.append(item)
            continue

        p = m.person
        if p["id"] in claimed:                       # same identity twice in one frame -> keep the best only
            results.append(item)
            continue
        claimed[p["id"]] = True
        item.update(label=p["name"], student_code=p["code"], status="recognized",
                    message="Recognised.")

        if not mark or session is None:
            item.update(status="no_session",
                        message="Recognised, but no attendance session is open - nothing recorded.")
        elif not att.student_in_session_scope(session, p):
            item.update(status="out_of_scope",
                        message=f"Not part of this session ({session['department'] or 'All'} / {session['class_name'] or 'All'}).")
        elif att.record_exists(db, session["id"], p["id"]):
            item.update(status="already", message="Attendance already recorded for this session.")
        else:
            confirmed, count = tracker.hit(p["id"], required)
            if not confirmed:
                item.update(status="verifying", message=f"Verifying ({count}/{required})...")
            else:
                try:
                    outcome = att.mark_present(db, session["id"], p["id"], confidence=m.score, source="face")
                    if outcome == "marked":
                        item.update(status="marked", message="Attendance marked: Present.")
                    else:
                        item.update(status="already", message="Attendance already recorded for this session.")
                except att.AttendanceError as exc:
                    item.update(status="error", message=str(exc))
        results.append(item)

    h, w = frame_bgr.shape[:2]
    return {"faces": results, "frame": {"width": w, "height": h},
            "gallery_people": len(gallery.people)}
