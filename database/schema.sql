-- =====================================================================
-- schema.sql - Face Recognition Attendance System (SQLite)
-- Safe to run many times (CREATE ... IF NOT EXISTS).
-- Foreign keys are enabled per-connection in database/db.py.
-- =====================================================================

-- 1. Administrators ----------------------------------------------------
CREATE TABLE IF NOT EXISTS administrators (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT    NOT NULL UNIQUE,
    password_hash        TEXT    NOT NULL,              -- salted PBKDF2 hash, never plain text
    full_name            TEXT    NOT NULL DEFAULT '',
    email                TEXT    NOT NULL DEFAULT '',
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0,1)),
    created_at           TEXT    NOT NULL,              -- UTC ISO-8601
    last_login_at        TEXT
);

-- 2. Students / employees ---------------------------------------------
CREATE TABLE IF NOT EXISTS students (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    student_code      TEXT NOT NULL UNIQUE,             -- the human-visible unique ID
    full_name         TEXT NOT NULL,
    department        TEXT NOT NULL,
    class_name        TEXT NOT NULL,                    -- class / semester / designation
    email             TEXT NOT NULL DEFAULT '',
    registration_date TEXT NOT NULL,                    -- local date YYYY-MM-DD
    consent_status    TEXT NOT NULL CHECK (consent_status IN ('granted','withdrawn')),
    consent_date      TEXT NOT NULL,                    -- UTC ISO-8601
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_students_name  ON students (full_name);
CREATE INDEX IF NOT EXISTS idx_students_group ON students (department, class_name);

-- 3. Face embeddings (biometric templates) -----------------------------
-- embedding = raw little-endian float32 bytes (dim * 4 bytes). No face photo is stored.
CREATE TABLE IF NOT EXISTS face_embeddings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    embedding     BLOB    NOT NULL,
    embedding_dim INTEGER NOT NULL,
    model_name    TEXT    NOT NULL,
    quality_score REAL,
    created_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_embeddings_student ON face_embeddings (student_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_model   ON face_embeddings (model_name);

-- 4. Attendance sessions ----------------------------------------------
CREATE TABLE IF NOT EXISTS attendance_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    session_date TEXT NOT NULL,                         -- local date YYYY-MM-DD
    department   TEXT,                                  -- NULL = everyone
    class_name   TEXT,                                  -- NULL = every class
    status       TEXT NOT NULL CHECK (status IN ('open','closed')),
    started_at   TEXT NOT NULL,                         -- UTC ISO-8601
    ended_at     TEXT,
    created_by   INTEGER REFERENCES administrators(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON attendance_sessions (session_date);
-- Only ONE session can be open at a time (enforced by the database itself).
CREATE UNIQUE INDEX IF NOT EXISTS one_open_session
    ON attendance_sessions (status) WHERE status = 'open';

-- 5. Attendance records -----------------------------------------------
CREATE TABLE IF NOT EXISTS attendance_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id        INTEGER NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
    student_id        INTEGER NOT NULL REFERENCES students(id)            ON DELETE CASCADE,
    status            TEXT NOT NULL CHECK (status IN ('Present','Absent')),
    source            TEXT NOT NULL CHECK (source IN ('face','manual')),
    marked_at         TEXT NOT NULL,                    -- UTC ISO-8601
    confidence        REAL,                             -- similarity score for face records
    is_corrected      INTEGER NOT NULL DEFAULT 0 CHECK (is_corrected IN (0,1)),
    original_status   TEXT,                             -- status before the first correction
    corrected_by      INTEGER REFERENCES administrators(id) ON DELETE SET NULL,
    corrected_at      TEXT,
    correction_reason TEXT,
    UNIQUE (session_id, student_id)                     -- <-- duplicate prevention lives HERE
);
CREATE INDEX IF NOT EXISTS idx_records_student ON attendance_records (student_id);

-- 6. Audit log ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id       INTEGER,
    admin_username TEXT,
    action         TEXT NOT NULL,
    entity_type    TEXT,
    entity_id      TEXT,
    details        TEXT,                                -- JSON text
    ip_address     TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action  ON audit_logs (action);

-- 7. Runtime settings (editable in the web UI) -------------------------
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
