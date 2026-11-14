"""Teacher names sent to the AI are always shortened: first name + initial of the last name ("Sara K.").
Names already stored in that form pass through unchanged. Use this for EVERY teacher name that goes into a prompt."""
import re

_SUFFIX = re.compile(r"\s*(\(\d+\))\s*$")  # "(2)" tells apart teachers who share a short name


def short_name(name: str) -> str:
    text = (name or "").strip()
    suffix = _SUFFIX.search(text)
    tail = f" {suffix.group(1)}" if suffix else ""
    words = _SUFFIX.sub("", text).split()
    if len(words) <= 1:
        return (words[0] if words else "") + tail
    last = words[-1]
    if last.endswith(".") and len(last) <= 3:  # already "Sara K."
        return " ".join(words) + tail
    letters = last[2:] if last.startswith("ال") and len(last) > 3 else last  # "المليفي" -> initial "م"
    return f"{words[0]} {letters[0]}." + tail
