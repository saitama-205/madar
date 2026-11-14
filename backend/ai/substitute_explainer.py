"""One friendly sentence saying why the top substitute was picked. The pick itself is made by substitutes.py;
the AI only words it. Always returns a sentence: if the AI is missing or fails, a template is used."""
from ai import llm
from ai.privacy import short_name

DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"]
TEMPLATES = {
    "same_subject_free": "{sub} also teaches {subject} and has no lesson in period {period}, so covering {klass} causes no clash.",
    "free_only": "{sub} has no lesson in period {period}. They do not usually teach {subject}, so this is supervision cover.",
}


def template_sentence(affected: dict, top: dict) -> str:
    return TEMPLATES[top["reason"]].format(sub=short_name(top["name"]), subject=affected["subject"],
                                           period=affected["period"], klass=affected["class"])


def explain_pick(absent_name: str, affected: dict, top: dict) -> tuple[str, str]:
    """Return (sentence, "ai" or "template"). Only shortened teacher names are put in the prompt."""
    fallback = template_sentence(affected, top)
    why = ("they teach this subject and are free in that period" if top["reason"] == "same_subject_free"
           else "they are free in that period, although they do not usually teach this subject")
    prompt = (f"Teacher {short_name(absent_name)} is absent on {DAY_NAMES[affected['day']]}. Their period "
              f"{affected['period']} lesson for class {affected['class']} ({affected['subject']}) needs cover. "
              f"{short_name(top['name'])} was chosen because {why}, and already has {top['day_load']} other lessons "
              "that day. Write ONE short friendly sentence (at most 25 words) for a school administrator saying "
              "why this teacher was chosen. Use only the facts given. No extra commentary.")
    try:
        text = llm.chat([{"role": "user", "content": prompt}], temperature=0.3, max_tokens=80).strip().strip('"')
    except llm.LLMError:
        return fallback, "template"
    return (text, "ai") if text else (fallback, "template")
