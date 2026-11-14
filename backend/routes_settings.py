"""GET / PUT /api/settings/ai: which AI model is used. A fixed whitelist only: no custom model, no API key."""
from fastapi import APIRouter
from pydantic import BaseModel

from ai import llm
from errors import ApiError

router = APIRouter(prefix="/api")


class AiSettingsIn(BaseModel):
    model: str


def current() -> dict:
    return {"model": llm.get_model(), "default": llm.default_model(),
            "models": [{"id": k, "label": v} for k, v in llm.ALLOWED_MODELS.items()],
            "ai_configured": llm.is_configured()}


@router.get("/settings/ai")
def get_ai_settings():
    return current()


@router.put("/settings/ai")
def set_ai_settings(body: AiSettingsIn):
    """Switch the model (kept in memory until the server restarts). Anything not in the whitelist is 400 invalid_model."""
    try:
        llm.set_model(body.model)
    except ValueError:
        raise ApiError(400, "invalid_model", "That model is not allowed. Choose one from the list in GET /api/settings/ai.")
    return current()
