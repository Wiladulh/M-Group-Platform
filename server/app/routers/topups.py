"""Cashier top-up endpoint."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.topup import TopupRequestPayload, TopupResponse
from app.security.device_auth import DeviceAuthInfo, require_device
from app.services.topup import process_cashier_topup

router = APIRouter(prefix="/api/v1", tags=["topups"])


@router.post("/topups", response_model=TopupResponse)
def create_topup(
    payload: TopupRequestPayload,
    request: Request,
    device_auth: DeviceAuthInfo = Depends(require_device),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> TopupResponse:
    """Process a member top-up initiated from a cashier device."""
    ip = request.client.host if request.client else None
    return process_cashier_topup(session, device_auth, payload, ip=ip)
