"""Excel import: GET /api/import/template, POST /api/import (preview only), POST /api/import/confirm (saves)."""
import sqlite3

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response

from errors import ApiError
from excel_import import MAX_FILE_BYTES, ConfirmIn, build_template, parse_upload, save_import, validate_import
from regen import regenerate
from routes_school import get_db

router = APIRouter(prefix="/api")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/import/template")
def template(db: sqlite3.Connection = Depends(get_db)):
    return Response(build_template(db), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="madar_template.xlsx"'})


@router.post("/import")
async def preview(file: UploadFile | None = File(default=None), db: sqlite3.Connection = Depends(get_db)):
    """Read the uploaded .xlsx and return what it contains. Nothing is saved."""
    if file is None:
        raise ApiError(400, "invalid_file", 'No file was sent. Send the .xlsx in the multipart form field "file".')
    content = await file.read(MAX_FILE_BYTES + 1)
    return parse_upload(content, file.filename or "", db)


@router.post("/import/confirm")
def confirm(body: ConfirmIn, db: sqlite3.Connection = Depends(get_db)):
    """Save the (possibly edited) preview and REPLACE all current data, including lessons and rules.
    Everything is checked first; if anything is wrong nothing is changed. Run Generate afterwards."""
    save_import(db, validate_import(body))
    return {"ok": True, **regenerate(db)}
