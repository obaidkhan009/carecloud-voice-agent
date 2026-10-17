"""FastAPI application: patient REST API + Vapi webhook + dashboard."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.logging_config import configure_logging
from app.routers import calls, health, patients, vapi
from app.schemas import envelope
from app.seed import seed
from app.services.patients import NotFoundError
from app.validation import FieldError

configure_logging()
log = logging.getLogger("app")
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # create_all is deliberate for a 3-hour build: schema is small and additive. Alembic is the next step.
    Base.metadata.create_all(bind=engine)
    if settings.seed_data:
        with SessionLocal() as db:
            n = seed(db)
            if n:
                log.info("seeded_patients", extra={"payload": {"count": n}})
    log.info("startup", extra={"payload": {"env": settings.app_env, "db": engine.url.get_backend_name()}})
    yield


app = FastAPI(
    title="CareCloud Voice Patient Registration API",
    version="1.0.0",
    description="REST API behind the voice registration agent. All responses use { data, error }.",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(patients.router)
app.include_router(calls.router)
app.include_router(vapi.router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


# ----------------------------------------------------------------------------- error envelope
def _error(status: int, code: str, message: str, details=None):
    return JSONResponse(status_code=status, content=envelope(None, {"code": code, "message": message, "details": details}))


@app.exception_handler(RequestValidationError)
async def _on_request_validation(_: Request, exc: RequestValidationError):
    details = []
    for err in exc.errors():
        loc = [str(p) for p in err["loc"] if p not in ("body", "query", "path")]
        msg = err["msg"].replace("Value error, ", "")
        details.append({"field": ".".join(loc) or "body", "message": msg})
    return _error(422, "validation_error", "Request validation failed", details)


@app.exception_handler(ValidationError)
async def _on_pydantic_validation(_: Request, exc: ValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"].replace("Value error, ", "")}
               for e in exc.errors()]
    return _error(422, "validation_error", "Validation failed", details)


@app.exception_handler(FieldError)
async def _on_field_error(_: Request, exc: FieldError):
    return _error(422, "validation_error", "Validation failed", [{"field": exc.field, "message": exc.message}])


@app.exception_handler(NotFoundError)
async def _on_not_found(_: Request, exc: NotFoundError):
    return _error(404, "not_found", str(exc))


@app.exception_handler(HTTPException)
async def _on_http(_: Request, exc: HTTPException):
    codes = {400: "bad_request", 401: "unauthorized", 404: "not_found", 405: "method_not_allowed", 422: "validation_error"}
    return _error(exc.status_code, codes.get(exc.status_code, "error"), str(exc.detail))


@app.exception_handler(Exception)
async def _on_unhandled(_: Request, exc: Exception):
    log.exception("unhandled_error")
    return _error(500, "internal_error", "Internal server error")
