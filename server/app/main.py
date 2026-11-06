"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import engine
from app.errors import DomainError
from app.logging import configure_logging
from app.routers.device import router as device_router
from app.routers.payments import router as payments_router
from app.routers.topups import router as topups_router

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Hold a database connection for the application lifespan."""
    connection = engine.connect()
    application.state.database_connection = connection
    try:
        yield
    finally:
        connection.close()
        engine.dispose()


app = FastAPI(
    title="M-Group Platform",
    version=settings.app_version,
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url="/redoc" if settings.enable_api_docs else None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
    lifespan=lifespan,
)


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.rendered_message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Permintaan tidak valid",
                "details": {"errors": exc.errors()},
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        error = {
            "code": detail["code"],
            "message": detail.get("message", "Request failed"),
            "details": detail.get("details", {}),
        }
    else:
        error = {
            "code": "VALIDATION_ERROR" if exc.status_code == 422 else "HTTP_ERROR",
            "message": str(detail),
            "details": {},
        }
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error},
        headers=exc.headers or {},
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Return the minimal public health status."""
    return {"status": "ok"}


app.include_router(device_router)
app.include_router(payments_router)
app.include_router(topups_router)
