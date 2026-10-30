# AI-Based Face Recognition Attendance System

Real-time face recognition attendance with an admin web dashboard, sessions, manual corrections with an audit trail,
analytics charts, and CSV / Excel reports. Built with **Python 3.12, Flask, OpenCV, InsightFace (ONNX Runtime, CPU), SQLite, Bootstrap, Chart.js**.

> This is a university project. Face recognition is a probabilistic aid, **not proof of identity**, and this version
> has **no liveness detection** (a printed photo or phone video of a person may be accepted). See `docs/`.

---------------------------------------------------------------------------

## 1. What is included

| Area | What you get |
|---|---|
| Admin security | Login/logout, PBKDF2 password hashing, sessions with timeout, CSRF tokens, login lock-out, security headers, forced password change for the default account |
| Registration | ID, name, department, class, email, consent checkbox, auto registration date |
| Face enrollment | Webcam capture (or photo upload), quality checks (face found, one face, size, sharpness, same-person consistency), duplicate-identity check. **Photos are never saved - only 512-number templates.** |
| Live recognition | Browser webcam -> server -> bounding box, name, status; "Unknown Person" for no reliable match; several faces per frame; N-frame confirmation before marking |
| Attendance | Sessions (open/close, one open at a time), Present records, **database UNIQUE constraint** blocks duplicates, unknown people are never recorded |
| Management | Search, date / department / class / status filters, absent list, per-person percentages, corrections with reason + audit log, "Recorded by camera" vs "Manual correction" badges |
| Dashboard | Totals, present/absent today, %, recent records, daily / weekly / monthly charts - **all from SQL queries** |
| Reports | Day / week / month / person / department-class -> CSV and Excel (3 sheets), timezone documented |
| Privacy | Consent, delete face data only (withdraw consent), delete person completely (cascade), `secure_delete` |
| Tests | 119 automated tests (118 run without a webcam; webcam test is opt-in) |

## 2. Project structure

```
face_attendance_system/
  app.py                    Flask application factory + entry point
  config.py                 all settings (env-overridable)
  facialprogram.py          your original script, completed: OpenCV desktop window version
  create_admin.py           create an admin / reset a password
  add_person.py             add one person from photo files (command line)
  known_faces/              drop photos here -> people are enrolled automatically
  seed_demo.py              enroll the sample photos (demo without a webcam)
  requirements.txt  pytest.ini  README.md
  database/   schema.sql, db.py
  models/     face_recognition_model.py      <- the ONLY file that talks to InsightFace
  services/   enrollment_service.py  recognition_service.py  attendance_service.py
              reporting_service.py   settings_service.py   audit_service.py
              security.py  validators.py  time_utils.py  dbutil.py
  routes/     auth_routes.py  student_routes.py  attendance_routes.py  dashboard_routes.py  report_routes.py
  templates/  base, login, dashboard, students, register_student, enroll_face, live_recognition,
              attendance, sessions, reports, profile, audit, error
  static/     css/style.css, js/*.js, vendor/ (Bootstrap, Chart.js, Icons - bundled, works offline)
  sample_images/   your test photos (used only by seed_demo.py and tests)
  instance/   attendance.db + secret_key are created here (never served, never in Git)
  tests/      conftest.py test_database.py test_auth.py test_students.py test_attendance.py
              test_recognition.py test_reports.py
  docs/       project_proposal.md  system_architecture.md  testing_report.md
              privacy_and_limitations.md  presentation_and_viva.md
```
Changes versus the proposed structure (and why): added `services/settings_service.py` (thresholds editable in the UI),
`services/security.py` (CSRF/login guard in one place), `services/audit_service.py`, `templates/profile|sessions|audit|enroll_face`
(required pages), vendored front-end libraries in `static/vendor` (demo works without internet), and `facialprogram.py` (your original desktop script).

## 3. Installation (Windows 10/11, PowerShell)

Requirements: **Python 3.12** (python.org, tick "Add Python to PATH"), a webcam, internet for the first run only (model download ~120 MB).

```powershell
# 1) go into the project folder
cd path\to\face_attendance_system

# 2) create and activate a virtual environment
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
#    If PowerShell blocks the script, run this once and retry:
#    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# 3) install dependencies (all are pre-built wheels: no C++ compiler needed)
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4) (optional but recommended) enroll the sample photos and add demo history for the charts
python seed_demo.py --history

# 5) run
python app.py
```
Open **http://127.0.0.1:5000** (use `127.0.0.1` or `localhost`; browsers only allow camera access there).
Default login: **admin / Admin@12345** - you are forced to choose a new password immediately.

On the first start the face model (`buffalo_s`) downloads into `C:\Users\<you>\.insightface\models`.
The page may say "model not available yet" for a minute; it is loading in the background.

## 4. How to use

1. **Register person** -> fill the form, tick consent -> you are taken to **Face enrollment**.
2. Enrollment: *Start camera* -> *Auto-capture 5* (turn your head slightly between shots) -> *Validate and save*.
   No webcam? use *Upload photos* (3+ clear photos of one person).
3. **Sessions** -> *Start session* (optionally limit to a department/class).
4. **Live recognition** -> *Start camera*. Green box + "PRESENT - marked" appears after the person is matched in 2 consecutive frames.
5. **Attendance records** -> filter, search, *Correct* (reason required, saved in **Audit log**).
6. **Sessions** -> *Close* when the class ends.  7. **Reports** -> choose type -> CSV / Excel.

Desktop alternative (OpenCV window, same logic and database): `python facialprogram.py --session "Lecture 1"`  (press `q` to quit).

### Adding people by dropping photos in a folder (no form, no code)
Put photos in the **`known_faces`** folder (next to `app.py`). People are enrolled automatically when `python app.py` starts,
or when you click **Sync from known_faces folder** on the *Registered people* page.
```
known_faces\Murtaza.jpg                 -> person "Murtaza"
known_faces\Niamatullah Hasand.png      -> person "Niamatullah Hasand"
known_faces\Ali (1).jpg, Ali (2).jpg    -> several photos of "Ali"
known_faces\Sara\1.jpg, Sara\2.jpg      -> sub-folder = one person
known_faces\CS-001__Murtaza.jpg         -> choose the ID yourself (ID, two underscores, name)
```
Nothing is trained: the pretrained model converts each photo to a numeric template. Already-enrolled people are skipped;
people who withdrew consent are never re-enrolled. Putting a photo there means the person agreed to it.
There is also `add_person.py` for the command line.

## 5. Running the tests

```powershell
pytest                    # 118 tests, no webcam needed (a fake face engine is used)
pytest -m model -s        # real-model tests on the photos in sample_images/ (needs the model download)
pytest -m "not model"     # skip real-model tests
$env:RUN_WEBCAM_TESTS = "1"; pytest -m webcam   # optional: tests a physical camera
```

## 6. Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `APP_TIMEZONE` | `Asia/Karachi` | Timestamps are stored in UTC and shown/exported in this zone |
| `FACE_MODEL_NAME` | `buffalo_s` | `buffalo_l` = larger/slower, often more accurate. **Changing it requires re-enrolling people** |
| `SIMILARITY_THRESHOLD` | `0.40` | Starting value; edit in *Profile & settings*. Tune on your own data |
| `DATABASE_PATH` | `instance/attendance.db` | |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `Admin@12345` | Only used when the database has no administrator |
| `SECRET_KEY` | auto-generated in `instance/secret_key` | |
| `SESSION_COOKIE_SECURE` | `0` | Set `1` when serving over HTTPS |

PowerShell example: `$env:APP_TIMEZONE = "Asia/Dubai"; python app.py`

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` |
| `pip install` fails / wrong Python | Check `python --version` shows 3.12.x inside the venv |
| Camera permission blocked | Click the camera icon in the address bar -> Allow; use `http://127.0.0.1:5000` |
| "Camera in use by another application" | Close Zoom/Teams/other browser tabs using the camera |
| "Face model is not available" | First run needs internet to download the model. Wait a minute, check `%USERPROFILE%\.insightface\models\buffalo_s` |
| Everyone shows "Unknown Person" | Enroll with more/better photos; lower the threshold slightly (e.g. 0.35) and re-test; check lighting |
| Wrong person recognised | Raise the threshold (e.g. 0.45-0.50); enroll better photos; never rely on the camera alone |
| "Port 5000 already in use" | Close the other copy, or change the port at the bottom of `app.py` |
| Forgot admin password | `python create_admin.py --username admin` |
| `facialprogram.py` black window | `python facialprogram.py --camera 1` |
| Reset everything | Stop the app, delete `instance\attendance.db*` |

## 8. Privacy summary (details in `docs/privacy_and_limitations.md`)

* Only numeric templates are stored; photos and video are processed in memory and discarded.
* Consent is required before enrollment and recorded; withdrawal deletes all templates.
* Pages and APIs need an administrator login; `instance/` and the database are not web-accessible.
* Manual attendance (corrections) is the alternative for anyone who declines face recognition.
* Not implemented: liveness / anti-spoofing, encryption of the database at rest, HTTPS (use a reverse proxy for real deployments).

## 9. Licensing note

Your code is yours. The InsightFace *library* is MIT-licensed, but the **pretrained model packs it downloads (buffalo_*) are
published by the InsightFace project for non-commercial research use** - fine for a university project, but check the current
terms at https://github.com/deepinsight/insightface before any commercial deployment. Bootstrap, Bootstrap Icons and Chart.js are MIT-licensed.
