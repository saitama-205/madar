"""Madar backend: FastAPI app. Run: cd backend, then `uvicorn main:app --reload` (see backend/README.md)."""
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# The database/ folder sits next to backend/, so put the repo root on the import path.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database.db import get_connection  # noqa: E402
from database.seed import seed, seed_if_empty  # noqa: E402
from errors import ApiError  # noqa: E402
from routes_school import router as school_router  # noqa: E402
from routes_absences import router as absences_router  # noqa: E402
from routes_analytics import router as analytics_router  # noqa: E402
from routes_rules import router as rules_router  # noqa: E402
from routes_timetable import router as timetable_router  # noqa: E402
from solver import generate_timetable  # noqa: E402

FRONTEND_DIR = ROOT / "frontend"

ERROR_CODES = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 409: "conflict", 422: "invalid_request"}


def error_response(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "message": message})


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_if_empty()  # first start (or a fresh Render disk): create tables and load the school's data
    if os.environ.get("MADAR_AUTO_GENERATE", "1") != "0":
        # Solve in the background so /api/health answers at once. Until it finishes, GET /api/timetable is empty.
        threading.Thread(target=generate_in_background, name="startup-generate", daemon=True).start()
    yield


def generate_in_background():
    """Build the first timetable after startup. Uses its own connection; failures are logged, never fatal."""
    conn = get_connection()
    try:
        has_lessons = conn.execute("SELECT 1 FROM lessons LIMIT 1").fetchone() is not None
        if not has_lessons:
            result = generate_timetable(conn)
            print(f"Startup timetable ready: {result}", flush=True)
    except Exception as exc:  # e.g. another Generate is already running, or the data is incomplete
        print(f"Startup timetable not generated: {exc!r}", flush=True)
    finally:
        conn.close()


def create_app(frontend_dir: Path = FRONTEND_DIR) -> FastAPI:
    app = FastAPI(title="Madar", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def on_api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.error, exc.message)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"] if p not in ("body", "query", "path"))
        return error_response(422, "invalid_request", f"{where}: {first['msg']}" if where else first["msg"])

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException):
        code = ERROR_CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def on_unexpected_error(request: Request, exc: Exception):
        return error_response(500, "server_error", "Something went wrong on the server.")

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.post("/api/reset")
    def reset():
        """Wipe every table and reload the original school data. Everything added since is lost."""
        conn = get_connection()
        try:
            seed(conn, reset=True)  # one transaction: if loading fails, nothing is wiped
        finally:
            conn.close()
        return {"ok": True}

    app.include_router(school_router)  # subjects, classes, teachers, timetable
    app.include_router(timetable_router)  # generate
    app.include_router(rules_router)  # rules
    app.include_router(absences_router)  # absences and substitutes
    app.include_router(analytics_router)  # analytics and AI insights

    # Must be LAST: "/" matches everything, so API routes above are checked first.
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app


app = create_app()

if __name__ == "__main__":  # `python main.py` also works; Render uses uvicorn directly (see render.yaml)
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))
