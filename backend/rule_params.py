"""The settings ("params") each rule kind must have. Used by the rules endpoints AND the solver, so they can
never disagree about what a valid rule is. Numbers must be real integers (a string like "3" is rejected)."""
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)  # unknown keys (typos) are errors, not ignored


class SubjectNotInPeriod(_Params):
    subject_id: int
    period: int = Field(ge=1, le=7)


class TeacherUnavailable(_Params):
    teacher_id: int
    day: int = Field(ge=0, le=4)
    period: int = Field(ge=1, le=7)


class PinLesson(_Params):
    class_id: int
    subject_id: int
    day: int = Field(ge=0, le=4)
    period: int = Field(ge=1, le=7)


RULE_KINDS = {
    "subject_not_in_period": SubjectNotInPeriod,
    "teacher_unavailable": TeacherUnavailable,
    "pin_lesson": PinLesson,
}


def parse_params(kind: str, params) -> _Params:
    """Return the validated params, or raise ValueError with a short human sentence."""
    model = RULE_KINDS.get(kind)
    if model is None:
        raise ValueError(f"unknown rule kind '{kind}' (use {', '.join(RULE_KINDS)}).")
    if not isinstance(params, dict):
        raise ValueError("params must be an object like {\"period\": 7}.")
    try:
        return model.model_validate(params)
    except ValidationError as e:
        first = e.errors()[0]
        field = ".".join(str(p) for p in first["loc"])
        if first["type"] == "missing":
            what = "is missing"
        elif first["type"] == "extra_forbidden":
            what = "is not a setting of this rule"
        elif first["type"] in ("greater_than_equal", "less_than_equal"):
            what = f"must be {RANGES[field]}"
        else:
            what = "must be a whole number"
        raise ValueError(f"'{field}' {what}.") from None


RANGES = {"day": "0 to 4 (Sunday to Thursday)", "period": "1 to 7"}
