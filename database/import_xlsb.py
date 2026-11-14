"""LOCAL-ONLY tool: turn the school's Excel timetable program (.xlsb) into seed files.

    pip install -r database/requirements-dev.txt
    python database/import_xlsb.py "source data/<file>.xlsb"

Writes two files:
    database/seed_data.json         teacher names shortened ("فاطمة ا."), safe to commit to GitHub
    database/seed_data.local.json   full teacher names, git-ignored, never commit

The Excel file itself is never committed (the "source data/" folder is git-ignored).
Re-run this only when the school's Excel data changes.
"""
import argparse
import collections
import glob
import json
import re
import sys
from pathlib import Path

from pyxlsb import open_workbook

HERE = Path(__file__).resolve().parent

# (department name as written in the Excel, English name, Arabic name). Order = subject id 1..10.
SUBJECTS = [
    ("التربية الإسلامية", "Islamic Education", "التربية الإسلامية"),
    ("اللغة العربية", "Arabic", "اللغة العربية"),
    ("اللغة الإنجليزية", "English", "اللغة الإنجليزية"),
    ("الرياضيات", "Math", "الرياضيات"),
    ("العلوم", "Science", "العلوم"),
    ("الاجتماعيات", "Social Studies", "الاجتماعيات"),
    ("الحاسوب", "Computer", "الحاسوب"),
    ("التربية البدنية", "PE", "التربية البدنية"),
    ("التربية الفنية", "Art", "التربية الفنية"),
    ("التربية الموسيقية", "Music", "التربية الموسيقية"),
]


def norm(text) -> str:
    """Remove Arabic stretching characters (tatweel) and collapse spaces."""
    return re.sub(r"\s+", " ", str(text).replace("ـ", "")).strip()


def clean_name(text) -> str:
    """'ر.ق هناء الجيماز' -> 'هناء الجيماز'; drops '*' marks and stray dots."""
    s = norm(str(text).replace("*", " "))
    s = re.sub(r"^ر\.ق\s*", "", s)
    s = re.sub(r"\s*\.\s*", " ", s)
    return norm(s)


def short_name(full: str) -> str:
    """First name + first letter of the last name (ignoring the 'ال' prefix): 'فاطمة المليفي' -> 'فاطمة م.'"""
    parts = full.split()
    if len(parts) == 1:
        return parts[0]
    last = parts[-1]
    core = last[2:] if last.startswith("ال") and len(last) > 3 else last
    return f"{parts[0]} {core[0]}."


def read_sheet(wb, name):
    with wb.get_sheet(name) as sh:
        return [{c.c: c.v for c in r if c.v not in (None, "")} for r in sh.rows()]


def build(xlsb_path: str):
    with open_workbook(xlsb_path) as wb:
        general = read_sheet(wb, "general")
        total = read_sheet(wb, "Total")

    dept_index = {norm(ar): i for i, (ar, _, _) in enumerate(SUBJECTS)}

    # --- teachers + lessons from the "general" sheet (one row per teacher, 35 slot columns) ---
    rows, dept = [], None
    for i, r in enumerate(general):
        if i < 11:
            continue
        if 1 in r and isinstance(r[1], str):
            dept = norm(r[1])
        if 3 in r and isinstance(r[3], str) and 2 in r:
            slots = {}
            for col, v in r.items():
                if 4 <= col <= 38 and isinstance(v, str) and "/" in v:
                    slots[((col - 4) // 7, (col - 4) % 7 + 1)] = v.strip()  # (day 0-4, period 1-7) -> class
            rows.append({"dept": dept, "full": clean_name(r[3]), "slots": slots})
    unknown = {r["dept"] for r in rows} - set(dept_index)
    assert not unknown, f"unknown department names: {unknown}"

    active = [r for r in rows if r["slots"]]
    print(f"teacher rows: {len(rows)}, with lessons: {len(active)} (skipped {len(rows) - len(active)} empty rows)")

    # --- classes ---
    class_names = sorted({c for r in active for c in r["slots"].values()},
                         key=lambda n: (int(n.split("/")[1]), int(n.split("/")[0])))
    classes = [{"name": n, "grade": int(n.split("/")[1])} for n in class_names]

    # --- checks: this is what the solver will rely on ---
    lessons = [(c, d, p, r["dept"], idx) for idx, r in enumerate(active) for (d, p), c in r["slots"].items()]
    assert len(lessons) == 700, f"expected 700 lessons, got {len(lessons)}"
    assert len(classes) == 20, f"expected 20 classes, got {len(classes)}"
    per_class = collections.Counter(c for c, *_ in lessons)
    assert all(v == 35 for v in per_class.values()), "every class must have 35 lessons"
    pair_teachers = collections.defaultdict(set)
    for c, d, p, dp, idx in lessons:
        pair_teachers[(c, dp)].add(idx)
    assert len(pair_teachers) == 200 and all(len(v) == 1 for v in pair_teachers.values()), \
        "each class+subject must have exactly one teacher"

    # --- hours per week per grade (must be identical for all 4 sections of a grade) ---
    counts = collections.defaultdict(collections.Counter)  # class -> dept -> n
    for c, d, p, dp, idx in lessons:
        counts[c][dp] += 1
    subject_hours = []
    for grade in range(1, 6):
        grade_classes = [c["name"] for c in classes if c["grade"] == grade]
        for dp, sid in dept_index.items():
            vals = {counts[c][dp] for c in grade_classes}
            assert len(vals) == 1, f"hours differ inside grade {grade} for {dp}: {vals}"
            subject_hours.append({"grade": grade, "subject": sid + 1, "per_week": vals.pop()})
        assert sum(h["per_week"] for h in subject_hours if h["grade"] == grade) == 35

    # --- teachers (ordered by subject, then Excel order) ---
    active.sort(key=lambda r: dept_index[r["dept"]])  # stable sort keeps Excel order inside a subject
    teachers = []
    for r in active:
        teachers.append({
            "full": r["full"],
            "subject": dept_index[r["dept"]] + 1,
            "classes": sorted({c for c in r["slots"].values()},
                              key=lambda n: (int(n.split("/")[1]), int(n.split("/")[0]))),
        })
    by_name = {t["full"]: i for i, t in enumerate(teachers)}
    assert len(by_name) == len(teachers), "two teachers share the same full name"

    # --- rules: "تخفيف نهاية2" = no lessons in periods 6-7, "تخفيف بداية1" = none in period 1 ---
    rules = []
    for r in total:
        note = str(r.get(8, ""))
        if 3 in r and isinstance(r[3], str) and "تخفيف" in note:
            name = clean_name(r[3])
            if name not in by_name:
                print(f"  note for unknown/inactive teacher skipped: {note.strip()!r}")
                continue
            if "نهاية" in note:
                periods, label = (6, 7), "Lighter end of day: no lessons in periods 6-7"
            elif "بداية" in note:
                periods, label = (1,), "Lighter start of day: no lesson in period 1"
            else:
                continue
            for day in range(5):
                for period in periods:
                    rules.append({"kind": "teacher_unavailable", "teacher_ref": by_name[name],
                                  "day": day, "period": period, "source_text": label})
    print(f"classes: {len(classes)}, lessons in school's timetable: {len(lessons)}, rules: {len(rules)}")

    subjects = [{"id": i + 1, "name": en, "name_ar": ar} for i, (_, en, ar) in enumerate(SUBJECTS)]
    return subjects, subject_hours, classes, teachers, rules


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsb", nargs="?", default=None, help='path to the .xlsb (default: the one in "source data/")')
    args = ap.parse_args()
    path = args.xlsb or (glob.glob(str(HERE.parent / "source data" / "*.xlsb")) or [None])[0]
    if not path:
        sys.exit('No .xlsb found. Put it in "source data/" or pass its path.')

    subjects, subject_hours, classes, teachers, rules = build(path)

    full = {"subjects": subjects, "subject_hours": subject_hours, "classes": classes, "rules": rules,
            "teachers": [{"name": t["full"], "subject": t["subject"], "classes": t["classes"]} for t in teachers]}

    # Public version: shortened names; if two teachers would look the same, add a number.
    seen = collections.Counter()
    public_teachers = []
    for t in teachers:
        s = short_name(t["full"])
        seen[s] += 1
        public_teachers.append({"name": s if seen[s] == 1 else f"{s} ({seen[s]})",
                                "subject": t["subject"], "classes": t["classes"]})
    public = dict(full, teachers=public_teachers)

    write(HERE / "seed_data.local.json", full)
    write(HERE / "seed_data.json", public)
    print("wrote database/seed_data.json (shortened names, commit this)")
    print("wrote database/seed_data.local.json (full names, git-ignored)")


if __name__ == "__main__":
    main()
