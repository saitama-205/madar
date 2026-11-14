"""POST /api/timetable/generate"""
import sqlite3

from fastapi import APIRouter, Depends

from routes_school import get_db
from solver import generate_timetable

router = APIRouter(prefix="/api")


@router.post("/timetable/generate")
def generate(db: sqlite3.Connection = Depends(get_db)):
    """Build a new timetable from the current database. Replaces all lessons if it succeeds."""
    return generate_timetable(db)
