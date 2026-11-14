"""English spellings of teacher names, from database/teacher_names_en.json (edit that file to correct a spelling).

The file is keyed by the shortened Arabic name ("فاطمة ج."), so it also works on a database that holds full names.
A name typed in Latin letters (a teacher added as "Sara K.") is already English and is returned as it is."""
import json
import re
from functools import lru_cache
from pathlib import Path

from ai.privacy import short_name

NAMES_FILE = Path(__file__).resolve().parents[1] / "database" / "teacher_names_en.json"
_ARABIC = re.compile("[؀-ۿ]")


@lru_cache(maxsize=1)
def _table() -> dict:
    try:
        return json.loads(NAMES_FILE.read_text(encoding="utf-8")).get("names", {})
    except (OSError, ValueError):
        return {}


def english_name(name: str) -> str | None:
    """'فاطمة ج.' -> 'Fatima J.'; 'Sara K.' -> 'Sara K.'; an Arabic name not in the file -> None."""
    if not name:
        return None
    if not _ARABIC.search(name):
        return name
    table = _table()
    return table.get(name) or table.get(short_name(name))
