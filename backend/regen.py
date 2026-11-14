"""Regenerate the timetable after any change to the data, and describe the outcome the same way everywhere.

`regenerate(db)` never raises: it returns {"generated", "violations", "warnings"} (plus "error", "lessons_count",
"seconds"). If the solve fails the old timetable is left exactly as it was (the solver only replaces lessons after
it has a complete answer), and "generated" is false with the reason in "warnings".
Set MADAR_AUTO_REGENERATE=0 to switch this off (tests do)."""
import os
import sqlite3

import solver
from errors import ApiError


def current_violations(db: sqlite3.Connection) -> list[str]:
    from analytics import compute  # local import: analytics imports solver too

    if db.execute("SELECT 1 FROM lessons LIMIT 1").fetchone() is None:
        return []
    return compute(db)["rule_check"]["violations"]


def regenerate(db: sqlite3.Connection) -> dict:
    if os.environ.get("MADAR_AUTO_REGENERATE", "1") == "0":
        return {"generated": False, "violations": current_violations(db),
                "warnings": ["Automatic regeneration is switched off."], "error": "regeneration_off"}
    try:
        result = solver.generate_timetable(db)
    except ApiError as e:
        return {"generated": False, "violations": current_violations(db),
                "warnings": [f"{e.message} The previous timetable was kept."], "error": e.error}
    except Exception:  # an unexpected solver problem must not undo the change that was just saved
        return {"generated": False, "violations": current_violations(db),
                "warnings": ["The timetable could not be generated. The previous timetable was kept."],
                "error": "generation_failed"}
    return {"generated": True, "violations": current_violations(db), "warnings": list(result.get("warnings", [])),
            "lessons_count": result["lessons_count"], "seconds": result["seconds"]}
