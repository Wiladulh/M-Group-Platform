"""Admin audit log helper."""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def _json_default(value: object) -> str:
    """Serialize datetimes as ISO 8601 and other unsupported values as strings."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def log_admin_action(
    db: Session,
    actor_id: str,
    action: str,
    entity: str,
    entity_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Add an admin audit entry without committing the caller's transaction."""
    row = AuditLog(
        actor_type="ADMIN",
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        before_json=json.dumps(before, default=_json_default) if before is not None else None,
        after_json=json.dumps(after, default=_json_default) if after is not None else None,
        ip=ip,
    )
    db.add(row)
    return row
