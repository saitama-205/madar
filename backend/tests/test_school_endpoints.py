"""subjects, classes, teachers, timetable (read) and POST classes / POST teachers."""


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def teacher_of(db, class_id, subject_id):
    """Teacher ids assigned to a class for a subject (must always be exactly one)."""
    return [r[0] for r in db.execute("""SELECT t.id FROM teachers t JOIN teacher_classes tc ON tc.teacher_id = t.id
                                        WHERE tc.class_id = ? AND t.subject_id = ?""", (class_id, subject_id))]


# ---------- reads ----------

def test_subjects(api):
    r = api.get("/api/subjects")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 10
    assert set(data[0]) == {"id", "name", "name_ar"}
    assert [s["name"] for s in data][:3] == ["Islamic Education", "Arabic", "English"]


def test_classes_are_sorted_by_grade_then_section(api):
    data = api.get("/api/classes").json()
    assert len(data) == 20
    assert set(data[0]) == {"id", "name", "grade"}
    assert [c["name"] for c in data][:5] == ["1/1", "2/1", "3/1", "4/1", "1/2"]
    assert [c["grade"] for c in data] == sorted(c["grade"] for c in data)


def test_teachers_have_class_ids(api):
    data = api.get("/api/teachers").json()
    assert len(data) == 79
    assert set(data[0]) == {"id", "name", "subject_id", "class_ids"}
    assert sum(len(t["class_ids"]) for t in data) == 200
    first = data[0]
    assert first["class_ids"] == sorted(first["class_ids"])


def test_timetable_is_empty_before_generating(api):
    assert api.get("/api/timetable", params={"class_id": 1}).json() == {"lessons": []}


def test_timetable_lesson_shape_and_filters(api):
    db = api.db
    link = db.execute("SELECT tc.class_id, tc.teacher_id, t.subject_id FROM teacher_classes tc "
                      "JOIN teachers t ON t.id = tc.teacher_id ORDER BY tc.class_id LIMIT 1").fetchone()
    db.executemany("INSERT INTO lessons (class_id, teacher_id, subject_id, day, period) VALUES (?, ?, ?, ?, ?)",
                   [(link[0], link[1], link[2], 3, 2), (link[0], link[1], link[2], 0, 5)])
    db.commit()

    by_class = api.get("/api/timetable", params={"class_id": link[0]}).json()["lessons"]
    assert [(x["day"], x["period"]) for x in by_class] == [(0, 5), (3, 2)]  # ordered by day, period
    assert set(by_class[0]) == {"class_id", "class", "teacher_id", "teacher", "subject_id", "subject", "day", "period"}
    assert by_class[0]["class"] == one(db, "SELECT name FROM classes WHERE id = ?", link[0])
    assert by_class[0]["teacher"] == one(db, "SELECT name FROM teachers WHERE id = ?", link[1])
    assert by_class[0]["subject"] == one(db, "SELECT name FROM subjects WHERE id = ?", link[2])

    by_teacher = api.get("/api/timetable", params={"teacher_id": link[1]}).json()["lessons"]
    assert len(by_teacher) == 2
    other = api.get("/api/timetable", params={"teacher_id": link[1] + 1}).json()["lessons"]
    assert other == []


def test_timetable_needs_exactly_one_filter(api):
    for params in ({}, {"class_id": 1, "teacher_id": 1}):
        r = api.get("/api/timetable", params=params)
        assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_timetable_unknown_or_bad_id(api):
    r = api.get("/api/timetable", params={"class_id": 999})
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = api.get("/api/timetable", params={"teacher_id": 999})
    assert r.status_code == 404
    r = api.get("/api/timetable", params={"class_id": "abc"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"


# ---------- POST /api/classes ----------

def test_cannot_add_a_class_when_all_four_sections_exist(api):
    r = api.post("/api/classes", json={"grade": 3})
    assert r.status_code == 409
    assert r.json()["error"] == "grade_full"
    assert one(api.db, "SELECT COUNT(*) FROM classes") == 20


def test_new_class_gets_the_next_free_section(api):
    api.db.execute("DELETE FROM classes WHERE name = '3/2'")  # free up section 3 of grade 2
    api.db.commit()
    r = api.post("/api/classes", json={"grade": 2})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "3/2" and body["grade"] == 2 and isinstance(body["id"], int)
    assert any(c["name"] == "3/2" for c in api.get("/api/classes").json())
    assert teacher_of(api.db, body["id"], 1) == []  # new class starts with no teachers


def test_bad_grade_is_rejected(api):
    for grade in (0, 6, "x"):
        r = api.post("/api/classes", json={"grade": grade})
        assert r.status_code == 422 and r.json()["error"] == "invalid_request"
    assert api.post("/api/classes", json={}).status_code == 422


# ---------- POST /api/teachers ----------

def test_new_teacher_takes_over_the_class_for_that_subject(api):
    db = api.db
    arabic = one(db, "SELECT id FROM subjects WHERE name = 'Arabic'")
    cls = one(db, "SELECT id FROM classes WHERE name = '1/1'")
    old = teacher_of(db, cls, arabic)
    assert len(old) == 1

    r = api.post("/api/teachers", json={"name": "  New Teacher ", "subject_id": arabic, "class_ids": [cls, cls]})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "New Teacher" and body["subject_id"] == arabic and body["class_ids"] == [cls]

    assert teacher_of(db, cls, arabic) == [body["id"]]  # still exactly one teacher per class and subject
    assert cls not in next(t for t in api.get("/api/teachers").json() if t["id"] == old[0])["class_ids"]
    assert len(api.get("/api/teachers").json()) == 80


def test_teacher_in_another_subject_does_not_take_over(api):
    db = api.db
    math = one(db, "SELECT id FROM subjects WHERE name = 'Math'")
    arabic = one(db, "SELECT id FROM subjects WHERE name = 'Arabic'")
    cls = one(db, "SELECT id FROM classes WHERE name = '1/1'")
    arabic_before = teacher_of(db, cls, arabic)
    api.post("/api/teachers", json={"name": "Math Helper", "subject_id": math, "class_ids": [cls]})
    assert teacher_of(db, cls, arabic) == arabic_before


def test_teacher_without_classes_is_allowed(api):
    r = api.post("/api/teachers", json={"name": "Spare", "subject_id": 1})
    assert r.status_code == 201 and r.json()["class_ids"] == []


def test_teacher_validation_and_atomicity(api):
    before = one(api.db, "SELECT COUNT(*) FROM teachers")
    r = api.post("/api/teachers", json={"name": "X", "subject_id": 999, "class_ids": []})
    assert r.status_code == 404 and r.json()["error"] == "subject_not_found"
    r = api.post("/api/teachers", json={"name": "X", "subject_id": 1, "class_ids": [1, 999]})
    assert r.status_code == 404 and r.json()["error"] == "class_not_found"
    for bad in ({"name": "   ", "subject_id": 1}, {"subject_id": 1}, {"name": "X"}):
        assert api.post("/api/teachers", json=bad).status_code == 422
    assert one(api.db, "SELECT COUNT(*) FROM teachers") == before
    # the failed attempts must not have stolen class 1's teacher either
    assert len(teacher_of(api.db, 1, 1)) == 1
