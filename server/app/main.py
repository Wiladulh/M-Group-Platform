"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import engine
from app.routers.device import router as device_router
from app.security.device_auth import DeviceAuthError

settings = get_settings()


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


@app.exception_handler(DeviceAuthError)
async def device_auth_error_handler(_request: Request, exc: DeviceAuthError):
    return JSONResponse(
        status_code=401,
        content={"error": {"code": exc.code, "message": exc.message, "details": {}}},
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
            "code": "VALIDATION_ERROR" if exc.status_code == 422 else "DEVICE_REVOKED",
            "message": str(detail),
            "details": {},
        }
    headers = exc.headers or {}
    return JSONResponse(status_code=exc.status_code, content={"error": error}, headers=headers)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Return the minimal public health status."""
    return {"status": "ok"}


app.include_router(device_router)
