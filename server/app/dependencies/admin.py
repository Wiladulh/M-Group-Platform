"""Browser administrator authentication dependency."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models.admin import AdminUser
from app.services.admin_auth import lookup_admin_session, touch_admin_session


def require_admin(request: Request, db: Session = Depends(get_session)) -> AdminUser:
    """Require a valid session cookie, refresh sliding expiry, and reject bearer auth."""
    if request.headers.get("Authorization"):
        raise HTTPException(status_code=401, detail="Authorization header tidak didukung")
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    session = lookup_admin_session(db, token) if token else None
    user = db.scalar(select(AdminUser).where(AdminUser.id == session.user_id)) if session else None
    if session is None or user is None:
        if request.headers.get("HX-Request", "").lower() == "true":
            raise HTTPException(status_code=200, headers={"HX-Redirect": "/admin/login"})
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    touch_admin_session(db, session, settings.session_idle_minutes)
    db.commit()
    request.state.admin_session = session
    return user
