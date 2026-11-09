"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import engine
from app.errors import DomainError
from app.logging import configure_logging
from app.routers.device import router as device_router
from app.routers.payments import router as payments_router
from app.routers.sync import router as sync_router
from app.routers.topups import router as topups_router
from app.services.admin_session_monitor import admin_session_monitor_loop
from app.services.background_tasks import pending_dispense_monitor_loop
from app.services.bind_expiry import bind_expiry_loop
from app.services.events import (
    CacheInvalidateEvent,
    CacheUpdateEvent,
    CardStatusChangedEvent,
    CatalogChangedEvent,
    _bus,
)
from app.services.offline_monitor import offline_monitor_loop
from app.ws.broadcast import broadcast_bus
from app.ws.connection_manager import manager
from app.ws.handlers import ws_device_endpoint
from app.ws.protocol import EnvelopeEnvelope

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Hold a database connection for the application lifespan."""
    import asyncio

    connection = engine.connect()
    application.state.database_connection = connection
    await broadcast_bus.start()
    background_tasks = [
        asyncio.create_task(bind_expiry_loop(application)),
        asyncio.create_task(offline_monitor_loop(application)),
        asyncio.create_task(pending_dispense_monitor_loop(application)),
        asyncio.create_task(admin_session_monitor_loop(application)),
    ]
    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        await broadcast_bus.stop()
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

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


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


@app.websocket("/ws/device")
async def ws_device(websocket: WebSocket):
    await ws_device_endpoint(websocket)


@app.get("/")
async def home(request: Request):
    """Render the application home page."""
    return templates.TemplateResponse(request, "base.html", {})


def _broadcast_domain_event(event):
    if isinstance(event, CacheUpdateEvent):
        for uid in event.uid_list:
            for device_pk in manager.connected_devices():
                broadcast_bus.enqueue(
                    EnvelopeEnvelope.build(
                        "cache.update",
                        {
                            "uid": uid,
                            "balance_snapshot": event.balance_snapshot,
                            "offline_allowance": event.offline_allowance.get(device_pk, 0),
                            "card_status": event.card_status,
                        },
                    ),
                    target_device_id_pk=device_pk,
                )
    elif isinstance(event, CacheInvalidateEvent):
        broadcast_bus.enqueue(
            EnvelopeEnvelope.build(
                "cache.invalidate", {"uid_list": event.uid_list, "all": event.all}
            )
        )
    elif isinstance(event, CardStatusChangedEvent):
        broadcast_bus.enqueue(
            EnvelopeEnvelope.build(
                "card.status_changed", {"uid": event.uid, "status": event.status}
            )
        )
    elif isinstance(event, CatalogChangedEvent):
        broadcast_bus.enqueue(EnvelopeEnvelope.build("catalog.changed", {"version": event.version}))


_bus.subscribe(CacheUpdateEvent, _broadcast_domain_event)
_bus.subscribe(CacheInvalidateEvent, _broadcast_domain_event)
_bus.subscribe(CardStatusChangedEvent, _broadcast_domain_event)
_bus.subscribe(CatalogChangedEvent, _broadcast_domain_event)

app.include_router(device_router)
app.include_router(payments_router)
app.include_router(sync_router)
app.include_router(topups_router)
