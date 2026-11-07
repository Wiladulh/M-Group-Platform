"""Device-authenticated offline synchronization and member cache endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Card, Member, OfflineAllowance
from app.schemas.sync import MemberCacheResponse, SyncBatch, SyncResponse
from app.security.device_auth import DeviceAuthInfo, require_device
from app.services.allowance import compute_cached_members_for_device
from app.services.cache_version import (
    get_member_cache_entry_version,
    get_member_cache_version,
)
from app.services.sync import SyncService

router = APIRouter(
    prefix="/api/v1/device",
    tags=["device"],
    dependencies=[Depends(require_device)],
)


@router.post("/sync", response_model=SyncResponse)
def sync_device_batch(
    batch: SyncBatch,
    device: DeviceAuthInfo = Depends(require_device),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> SyncResponse:
    """Synchronize one ordered offline transaction batch."""
    return SyncService(session).process_batch(device, batch)


@router.get("/member-cache", response_model=MemberCacheResponse)
def get_member_cache(
    since: int = Query(default=0, ge=0),
    device: DeviceAuthInfo = Depends(require_device),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> MemberCacheResponse:
    """Return the top-100 device cache entries changed after a global version."""
    current = get_member_cache_version(session)
    if since > current:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Member cache version is ahead of the server",
                "details": {"since": since, "cache_version": current},
            },
        )
    if since == current:
        return MemberCacheResponse(cache_version=current, entries=[])

    member_ids = compute_cached_members_for_device(session, device.id, limit=100)
    if not member_ids:
        return MemberCacheResponse(cache_version=current, entries=[])
    rows = session.execute(
        select(OfflineAllowance, Member, Card)
        .join(Member, Member.id == OfflineAllowance.member_id)
        .join(Card, Card.member_id == Member.id)
        .where(
            OfflineAllowance.device_id == device.id,
            Member.id.in_(member_ids),
        )
        .order_by(Member.member_code, Card.uid)
    ).all()
    entries = []
    for allowance, member, card in rows:
        entry_version = get_member_cache_entry_version(session, member.id, device.id)
        if entry_version <= since:
            continue
        entries.append({
            "uid": card.uid,
            "member_code": member.member_code,
            "name": member.full_name,
            "balance_snapshot": member.balance,
            "snapshot_ts": allowance.computed_at.isoformat().replace("+00:00", "Z"),
            "offline_allowance": allowance.amount,
            "card_status": card.status,
            "entry_version": entry_version,
        })
    return MemberCacheResponse(cache_version=current, entries=entries)
