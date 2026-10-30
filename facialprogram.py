"""
facialprogram.py - desktop (OpenCV window) live recognition.

This is your original script, completed. The original had an empty check_face();
now it uses the same recognition + attendance code as the web application.

Usage (PowerShell, inside the project folder, venv active):
    python facialprogram.py                       # use the open session (if any)
    python facialprogram.py --session "Lecture 1" # open a session first
    python facialprogram.py --camera 1            # use another camera
Press  q  in the video window to quit.
"""
import argparse
import sys
import threading

import cv2

from config import Config
from database import db as database
from models.face_recognition_model import get_engine
from services import attendance_service as att
from services import recognition_service as rec
from services import time_utils

COLORS = {"marked": (60, 160, 40), "already": (200, 120, 30), "verifying": (0, 150, 240),
          "recognized": (0, 150, 240), "no_session": (0, 150, 240), "out_of_scope": (140, 140, 140),
          "unknown": (50, 50, 230), "error": (160, 40, 150)}

state = {"result": None, "busy": False, "error": None}
lock = threading.Lock()


def open_camera(index: int):
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY   # DirectShow is the most reliable on Windows
    cap = cv2.VideoCapture(index, backend)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return cap


def check_face(frame):
    """Runs in a background thread so the video window never freezes."""
    conn = database.connect(Config.DATABASE)          # SQLite connections must not be shared between threads
    try:
        session = att.get_open_session(conn)
        result = rec.process_frame(conn, frame, session)
        result["session"] = session["name"] if session else None
        with lock:
            state["result"], state["error"] = result, None
    except Exception as exc:                          # never crash the video loop
        with lock:
            state["error"] = str(exc)
    finally:
        conn.close()
        with lock:
            state["busy"] = False


def draw(frame, result):
    for f in result["faces"]:
        x1, y1, x2, y2 = f["bbox"]
        color = COLORS.get(f["status"], (50, 50, 230))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f"{f['label']} - {f['status']}" + (f" ({f['score']:.2f})" if f["score"] is not None else "")
        cv2.rectangle(frame, (x1, max(0, y1 - 22)), (x1 + 9 * len(text) // 1, y1), color, -1)
        cv2.putText(frame, text, (x1 + 4, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--session", help="open a new attendance session with this name if none is open")
    ap.add_argument("--every", type=int, default=6, help="analyse every N-th frame (default 6)")
    args = ap.parse_args()

    time_utils.configure(Config.TIMEZONE)
    database.init_db(Config.DATABASE)
    conn = database.connect(Config.DATABASE)
    if args.session and att.get_open_session(conn) is None:
        att.create_session(conn, args.session, None, None, {"id": None, "username": "desktop-script"})
        print(f"Session '{args.session}' started.")
    open_s = att.get_open_session(conn)
    conn.close()
    print("Open session:", open_s["name"] if open_s else "NONE (faces are recognised but nothing is recorded)")
    print("Loading face model (the first run downloads ~120 MB)...")
    get_engine().warm_up()

    capture = open_camera(args.camera)
    if not capture.isOpened():
        print("ERROR: cannot open the camera. Close other apps that use it, or try --camera 1.")
        return 1
    counter = 0
    print("Camera running. Press q in the window to quit.")
    while True:
        ret, frame = capture.read()
        if not ret:
            print("Camera frame could not be read."); break
        with lock:
            start = (counter % args.every == 0) and not state["busy"]
            if start:
                state["busy"] = True
        if start:
            threading.Thread(target=check_face, args=(frame.copy(),), daemon=True).start()
        counter += 1
        with lock:
            result, err = state["result"], state["error"]
        if result:
            draw(frame, result)
            banner = f"Session: {result['session']}" if result["session"] else "NO OPEN SESSION - nothing is recorded"
        else:
            banner = "Starting..."
        if err:
            banner = "Error: " + err[:60]
        cv2.putText(frame, banner, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow("Face Attendance (q = quit)", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    capture.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
