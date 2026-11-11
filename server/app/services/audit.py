"""Admin audit log helper."""

import json

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


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
        before_json=json.dumps(before, default=str) if before is not None else None,
        after_json=json.dumps(after, default=str) if after is not None else None,
        ip=ip,
    )
    db.add(row)
    return row
