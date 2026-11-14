-- Madar database schema (SQLite). Tables follow CONTRACT.md exactly.
-- Days: 0=Sunday .. 4=Thursday. Periods: 1..7.

CREATE TABLE IF NOT EXISTS subjects (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    name_ar TEXT
);

CREATE TABLE IF NOT EXISTS subject_hours (
    grade      INTEGER NOT NULL,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    per_week   INTEGER NOT NULL CHECK (per_week >= 0),
    PRIMARY KEY (grade, subject_id)
);

CREATE TABLE IF NOT EXISTS classes (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,              -- "section/grade", e.g. "2/5"
    grade INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 5)
);

CREATE TABLE IF NOT EXISTS teachers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    subject_id INTEGER NOT NULL REFERENCES subjects(id)
);

CREATE TABLE IF NOT EXISTS teacher_classes (
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    PRIMARY KEY (teacher_id, class_id)
);

CREATE TABLE IF NOT EXISTS lessons (
    id         INTEGER PRIMARY KEY,
    class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id),
    day        INTEGER NOT NULL CHECK (day BETWEEN 0 AND 4),
    period     INTEGER NOT NULL CHECK (period BETWEEN 1 AND 7),
    -- Safety nets (hard rules 1 and 2): one lesson per class per slot,
    -- and a teacher is never in two places at once.
    UNIQUE (class_id, day, period),
    UNIQUE (teacher_id, day, period)
);

CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,               -- subject_not_in_period | teacher_unavailable | pin_lesson
    params      TEXT NOT NULL CHECK (json_valid(params)),
    source_text TEXT
);
