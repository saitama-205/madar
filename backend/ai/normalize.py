"""Tidy up what the AI (or a user) wrote so Arabic and English requests both work.

The AI is asked for English day/subject names and plain digits, but for an Arabic request it may answer
"الأحد", "الرياضيات" or "٣". These helpers map such variants onto the exact values our database uses.
Nothing here is guessed: anything not recognised comes back as None / unchanged so the caller can reject it."""
import re
import unicodedata

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_MARKS = re.compile("[ً-ٰٟـ]")  # diacritics and tatweel
_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_FILLER = {"يوم", "مادة", "ماده", "حصة", "حصه", "صف", "فصل"}


def key(text) -> str:
    """Forgiving comparison key: no diacritics, one kind of alef, no leading 'ال', no filler words,
    lower case, ASCII digits. 'الأحد' and 'احد' give the same key."""
    s = unicodedata.normalize("NFKC", str(text if text is not None else "")).translate(_DIGITS)
    s = _MARKS.sub("", s).translate(_LETTERS).casefold()
    words = [w for w in re.split(r"[\s_\-]+", s.strip()) if w]
    words = [w[2:] if w.startswith("ال") and len(w) > 3 else w for w in words]
    return " ".join(w for w in words if w not in _FILLER)


DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"]  # index = day number in the database
_DAY_WORDS = {
    0: ("sunday", "sun", "الاحد", "احد"),
    1: ("monday", "mon", "الاثنين", "الاتنين", "اثنين", "اتنين"),
    2: ("tuesday", "tue", "tues", "الثلاثاء", "ثلاثاء"),
    3: ("wednesday", "wed", "الاربعاء", "اربعاء"),
    4: ("thursday", "thu", "thur", "thurs", "الخميس", "خميس"),
}

# Extra words people use for our subject names (keyed by the English name stored in the database).
_SUBJECT_WORDS = {
    "Islamic Education": ("islamic studies", "islamic", "religion", "quran", "اسلاميه", "تربيه اسلاميه", "دين", "ديني", "قران"),
    "Arabic": ("arabic", "عربي", "عربيه", "لغه عربيه", "لغتي"),
    "English": ("english", "انجليزي", "انجليزيه", "لغه انجليزيه", "انكليزي", "انكليزيه"),
    "Math": ("math", "maths", "mathematics", "رياضيات", "حساب"),
    "Science": ("science", "علوم"),
    "Social Studies": ("social studies", "social", "اجتماعيات", "دراسات اجتماعيه", "اجتماعي"),
    "Computer": ("computer", "computers", "ict", "حاسوب", "حاسب", "حاسب الي", "كمبيوتر"),
    "PE": ("pe", "p.e.", "physical education", "sport", "sports", "gym", "تربيه بدنيه", "بدنيه", "رياضه بدنيه"),
    "Art": ("art", "arts", "تربيه فنيه", "فنيه", "فنون", "رسم"),
    "Music": ("music", "موسيقي", "موسيقى", "تربيه موسيقيه", "موسيقيه"),
}


def number(value) -> int | None:
    """'٣' / '3' / 3.0 / 3 -> 3. None if it is not a whole number (booleans are not numbers)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.translate(_DIGITS).strip()
        if re.fullmatch(r"-?\d+", s):
            return int(s)
    return None


def day(value) -> int | None:
    """'الأحد' / 'Sun' / 'يوم الاثنين' / 0 -> 0..4 (Sunday = 0). None if not a school day."""
    n = number(value)
    if n is not None and not isinstance(value, str):
        return n if 0 <= n <= 4 else None
    k = key(value)
    for index, words in _DAY_WORDS.items():
        if k in {key(w) for w in words}:
            return index
    return None


def period(value) -> int | None:
    """'٣' / '3rd' / 3 -> 3 when it is 1..7, else None."""
    n = number(value)
    if n is None and isinstance(value, str):
        m = re.fullmatch(r"(\d)(?:st|nd|rd|th)?", value.translate(_DIGITS).strip().lower())
        n = int(m.group(1)) if m else None
    return n if n is not None and 1 <= n <= 7 else None


def subject_id(value, subjects) -> int | None:
    """Match an English/Arabic subject name or alias to a subject id. `subjects` = rows with id, name, name_ar.
    Also accepts the id itself."""
    n = number(value)
    if n is not None and any(s["id"] == n for s in subjects):
        return n
    k = key(value)
    if not k:
        return None
    for s in subjects:
        words = {key(s["name"]), key(s["name_ar"] or "")} | {key(w) for w in _SUBJECT_WORDS.get(s["name"], ())}
        if k in words:
            return s["id"]
    return None


def class_name(value) -> str | None:
    """'٢/٥' / '2/5' / '2 / 5' -> '2/5'. None if it does not look like a class name."""
    if not isinstance(value, str):
        return None
    s = value.translate(_DIGITS).strip().replace(" ", "")
    return s if re.fullmatch(r"\d+/\d+", s) else None
