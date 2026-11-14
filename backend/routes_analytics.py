"""GET /api/analytics (numbers computed in Python) and POST /api/analytics/insights (AI explains those numbers)."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ai.insights import explain_metrics
from analytics import compute
from routes_school import get_db

router = APIRouter(prefix="/api")


class InsightsIn(BaseModel):
    language: Literal["en", "ar"] = "en"


@router.get("/analytics")
def analytics(db: sqlite3.Connection = Depends(get_db)):
    return compute(db)


@router.post("/analytics/insights")
def insights(body: InsightsIn | None = None, db: sqlite3.Connection = Depends(get_db)):
    """Recompute the same metrics, send only those to the AI, return its explanation. Nothing is changed."""
    return explain_metrics(compute(db), (body or InsightsIn()).language)
