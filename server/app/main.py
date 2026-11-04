"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.config import get_settings
from app.db import engine


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


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Return the minimal public health status."""
    return {"status": "ok"}
