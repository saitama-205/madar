# Database

Owner: saitama-205

SQLite file `database/madar.db` (git-ignored, created automatically). Tables are defined in `CONTRACT.md`.

| File | What it does |
| --- | --- |
| `schema.sql` | The 7 contract tables, plus UNIQUE constraints that stop a class or teacher being double-booked |
| `db.py` | `get_connection()` (rows by column name, foreign keys on) and `init_db()`. Set `MADAR_DB` to use another file (tests do) |
| `seed.py` | Loads the real school: 10 subjects, hours per grade, 20 classes, 79 teachers with their classes, and the "lighter teacher" rules. No lessons: the solver creates those |
| `seed_data.json` | The data `seed.py` loads. **Committed**, teachers shown as first name + initial |
| `seed_data.local.json` | Same data with full teacher names. **Git-ignored**, only on the owner's machine. `seed.py` prefers it when present |
| `import_xlsb.py` | Local-only tool that rebuilds both JSON files from the school's Excel (`source data/`, also git-ignored) |

```
python database/seed.py            # fill an empty database
python database/seed.py --reset    # wipe everything and re-fill
python database/import_xlsb.py     # only when the Excel data changes (pip install -r database/requirements-dev.txt)
```

The backend calls `seed_if_empty()` on startup, so a fresh deploy fills itself.
