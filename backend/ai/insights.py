"""Ask the AI to EXPLAIN the metrics Python computed (analytics.compute). The AI gets only those numbers
(teacher names shortened), never raw data, and its answer may only contain numbers that appear in them."""
import json
import re

from ai import llm
from ai.normalize import _DIGITS
from ai.privacy import short_name
from errors import ApiError

LANGUAGES = {"en": "English", "ar": "Arabic"}
ALWAYS_OK = set(map(str, range(0, 8)))  # day and period numbers are always fine to mention

PROMPT = """You help a school administrator understand a timetable. You are given METRICS that were already
computed by software. Explain them; do NOT calculate anything.

Rules:
- Use ONLY numbers that appear in the metrics. Never add, subtract, average, round or estimate.
- Teachers are named as given (short names). Days are 0=Sunday to 4=Thursday; periods are 1 to 7.
- You can only suggest ideas as text. Nothing is changed automatically.
- Write in {language}.

Answer ONLY with JSON: {{"summary": "one short paragraph", "recommendations": ["one sentence", ...]}}
(at most 4 recommendations)."""


def metrics_for_ai(metrics: dict) -> dict:
    """The metrics with every teacher name shortened, plus a few headline figures computed here in Python."""
    load = [{**t, "teacher": short_name(t["teacher"])} for t in metrics["teacher_load"]]
    gaps = [{**g, "teacher": short_name(g["teacher"])} for g in metrics["teacher_gaps"]]
    busiest = sorted(load, key=lambda t: (-t["per_week"], t["teacher_id"]))[:5]
    highlights = {
        "teachers": len(load),
        "classes": len(metrics["class_load"]),
        "busiest_teachers": [{"teacher": t["teacher"], "per_week": t["per_week"]} for t in busiest],
        "max_per_week": max((t["per_week"] for t in load), default=0),
        "min_per_week": min((t["per_week"] for t in load), default=0),
        "teacher_days_with_gaps": len(gaps),
        "total_gap_periods": sum(g["gap_periods"] for g in gaps),
        "rule_violations": len(metrics["rule_check"]["violations"]),
    }
    return {"highlights": highlights, "teacher_load": load, "teacher_gaps": gaps,
            "hard_subjects_by_period": metrics["hard_subjects_by_period"], "class_load": metrics["class_load"],
            "rule_check": metrics["rule_check"]}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text.translate(_DIGITS)))


def _bad_numbers(answer: dict, allowed: set[str]) -> set[str]:
    texts = [answer["summary"], *answer["recommendations"]]
    return {n for t in texts for n in _numbers(t)} - allowed


def _read(raw: str) -> dict:
    data = llm.extract_json(raw)
    summary, recs = data.get("summary"), data.get("recommendations", [])
    if not isinstance(summary, str) or not summary.strip() or not isinstance(recs, list) \
            or not all(isinstance(r, str) for r in recs):
        raise llm.LLMError("The AI did not answer with the expected format.")
    return {"summary": summary.strip(), "recommendations": [r.strip() for r in recs if r.strip()][:4]}


def explain_metrics(metrics: dict, language: str = "en") -> dict:
    """Return {"summary", "recommendations"}. Raises ApiError 503 (AI missing/down) or 502 (it broke the numbers rule)."""
    payload = json.dumps(metrics_for_ai(metrics), ensure_ascii=False, separators=(",", ":"))
    allowed = _numbers(payload) | ALWAYS_OK
    messages = [{"role": "system", "content": PROMPT.format(language=LANGUAGES[language])},
                {"role": "user", "content": "METRICS:\n" + payload}]
    try:
        for attempt in range(2):
            answer = _read(llm.chat(messages, temperature=0.2, max_tokens=700))
            bad = _bad_numbers(answer, allowed)
            if not bad:
                return answer
            messages.append({"role": "user", "content": "Your answer used numbers that are not in the metrics ("
                             + ", ".join(sorted(bad)) + "). Answer again using only numbers from the metrics."})
    except llm.LLMError as e:
        raise ApiError(503, "ai_unavailable", str(e)) from e
    raise ApiError(502, "ai_bad_answer", "The AI's answer used numbers that are not in the metrics, so it was discarded. Try again.")
