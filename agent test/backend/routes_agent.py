"""POST /api/agent: the Madar assistant. It looks things up and prepares proposals; it never changes data.
The app shows each proposal; when the admin approves one, the app sends proposal.request to the existing endpoint."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai.agent import run_agent
from routes_school import get_db

router = APIRouter(prefix="/api")


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class AgentIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    language: Literal["en", "ar"] = "en"
    history: list[Turn] = Field(default_factory=list, max_length=10)  # earlier turns, so follow-up answers work


@router.post("/agent")
def agent(body: AgentIn, db: sqlite3.Connection = Depends(get_db)):
    """{"reply": str, "proposals": [{id, type, description, impact, request}], "steps": [{tool, summary}]}"""
    return run_agent(db, body.message, body.language, [t.model_dump() for t in body.history])
