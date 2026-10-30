# Testing Report

Everything in section 1 was actually run; section 3 is a **plan**, not results.

## 1. Automated software tests (run on 29 Oct 2026, Python 3.12, pytest)
Command: `pytest` -> **110 passed, 1 skipped** (the skipped test needs a physical webcam: `RUN_WEBCAM_TESTS=1`).

| Requirement | Test file / examples | Result |
|---|---|---|
| Administrator login / logout / wrong password / unknown user | `test_auth.py` | pass |
| Unauthorised access (11 pages, 3 APIs, 6 POST actions) | `test_auth.py` | pass |
| CSRF protection, brute-force lock-out, open-redirect, headers, cookie flags, forced password change, weak passwords | `test_auth.py` | pass |
| Student registration, validation, consent, XSS escaping, SQL-injection text, search | `test_students.py` | pass |
| Duplicate student IDs | `test_students.py`, `test_database.py` | pass |
| Face enrollment (quality, no-face, multi-face, mixed people, duplicate identity, consent, re-enrollment) | `test_students.py` | pass |
| Biometric deletion and cascade delete | `test_students.py`, `test_database.py` | pass |
| Recognition of known person / rejection of unknown / empty gallery / ambiguity / threshold | `test_recognition.py`, `test_attendance.py` | pass |
| Duplicate attendance prevention (DB constraint) | `test_database.py`, `test_attendance.py` | pass |
| Sessions (create, close, only one open, scope) | `test_attendance.py`, `test_database.py` | pass |
| Corrections + audit trail, camera vs manual distinction | `test_attendance.py` | pass |
| Date / department / class filters, absent logic, percentages | `test_attendance.py` | pass |
| Dashboard numbers from database (and empty state) | `test_attendance.py` | pass |
| Reports day/week/month/person/group, CSV, Excel, timezone, formula-injection safety | `test_reports.py` | pass |
| Database failures handled safely | `test_database.py`, `test_attendance.py` | pass |

**Testing without a webcam:** most tests use a `FakeEngine` (see `tests/conftest.py`) that converts synthetic images into deterministic embeddings, so identities, unknown people and multiple faces can be simulated. Tests marked `model` use the real InsightFace model and the photos in `sample_images/` (`pytest -m model -s`).

## 2. Real-model observations (small, informal - NOT an accuracy evaluation)
Data: 5 photos (4 of one person, 1 of another), model `buffalo_s`, CPU. One authoring machine (Linux sandbox, 1 CPU core); your laptop will differ.
* Face detected exactly once in all 5 photos (detector confidence 0.78-0.85).
* Cosine similarity between different photos of the same person: **0.59 - 0.71**. Between the two different people: **0.01 - 0.09**.
* Held-out check (3 photos enrolled, a 4th photo tested): same person scored **0.676** (accepted at 0.40); the other person scored **0.096** (rejected).
* A deliberately blurred copy was rejected at enrollment (sharpness 3.4 vs 260-800 for sharp photos); a 22-px face was rejected as too small.
* Average analysis time: **about 45 ms per 640x480 frame** on the authoring machine (5-frame average after warm-up). End-to-end HTTP recognition requests took about 55-85 ms locally.
* End-to-end run against the live server: login, forced password change, all pages HTTP 200, session creation, 3 frames per person -> `verifying`, `marked`, `already`; blank frame -> no faces; CSV and Excel exports returned.

**Why this is not enough to claim accuracy:** two people and five photos cannot estimate false-acceptance or false-rejection rates. The 0.40 threshold is a starting value consistent with these numbers, not a validated operating point.

## 3. Evaluation plan to complete (fill the tables with YOUR measurements)
Protocol: (1) recruit N consenting volunteers (suggest 10+); enroll each with 5 photos; (2) collect separate test images/video per volunteer under each condition; include non-enrolled people as impostors; (3) run recognition at thresholds 0.25...0.60; (4) count outcomes; (5) report sample sizes.

| Threshold | Genuine attempts | Impostor attempts | False rejects | False accepts | FRR | FAR | Precision | Recall |
|---|---|---|---|---|---|---|---|---|
| 0.30 | _ | _ | _ | _ | _ | _ | _ | _ |
| 0.40 | _ | _ | _ | _ | _ | _ | _ | _ |
| 0.50 | _ | _ | _ | _ | _ | _ | _ | _ |

Formulas: FAR = false accepts / impostor attempts; FRR = false rejects / genuine attempts; precision = TP / (TP + FP); recall = TP / (TP + FN).

| Condition | Detection rate | Recognition rate | Notes |
|---|---|---|---|
| Bright light | _ | _ | |
| Normal indoor | _ | _ | |
| Dim | _ | _ | |
| Backlit | _ | _ | |
| 0 / 15 / 30 / 45 degrees | _ | _ | |
| 0.5 / 1 / 2 / 3 m | _ | _ | |

Latency (target laptop): mean _ ms, 95th percentile _ ms.  Attendance recording success in live trials: _ / _.
