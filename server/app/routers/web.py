"""Administrator browser routes."""

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from app.config import get_settings
from app.db import get_session
from app.dependencies.admin import require_admin
from app.models import AuditLog, Device, Member, TopUpRequest, Transaction\nfrom app.models.admin import AdminSession, AdminUser
from app.security.csrf import generate_csrf_token, verify_csrf_token
from app.services.admin_auth import (
    create_admin_session,
    lookup_admin_session,
    revoke_admin_session,
    revoke_other_sessions,
)
from app.services.audit import log_admin_action
from app.services.rate_limit import check_login_rate_limit, record_login_attempt

router = APIRouter(tags=["admin-web"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
hasher = PasswordHasher()


def _key() -> bytes:
    encoded = get_settings().data_key.get_secret_value().translate(str.maketrans("-_", "+/"))
    return base64.b64decode(encoded)


def _token(context: str) -> str:
    return generate_csrf_token(_key(), context)


def _valid(token: str, context: str) -> bool:
    return verify_csrf_token(token, _key(), context)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _bad_form(request: Request, template: str, error: str, status: int, user=None):
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "csrf_token": _token("login-csrf:" if user is None else "admin-csrf:"),
            "error": error,
        },
        status_code=status,
    )


@router.get("/admin/login")
def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"csrf_token": _token("login-csrf:"), "error": None},
    )


@router.post("/admin/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_session),  # noqa: B008
):
    settings = get_settings()
    if not _valid(csrf_token, "login-csrf:"):
        return _bad_form(request, "admin/login.html", "Token CSRF tidak valid", 403)
    ip = _ip(request)
    if not check_login_rate_limit(
        db,
        ip,
        username,
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_window_minutes,
    ):
        return _bad_form(request, "admin/login.html", "Terlalu banyak percobaan login", 429)
    user = db.scalar(select(AdminUser).where(AdminUser.username == username))
    valid = False
    if user is not None:
        try:
            valid = hasher.verify(user.password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            valid = False
    record_login_attempt(db, ip, username, valid)
    if not valid or user is None:
        db.commit()
        return _bad_form(request, "admin/login.html", "Username atau password salah", 401)
    token, _ = create_admin_session(
        db, user, ip, request.headers.get("user-agent"), settings.session_idle_minutes
    )
    user.last_login_at = datetime.now(UTC)
    log_admin_action(db, str(user.id), "LOGIN", "admin_session", ip=ip)
    db.commit()
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
        max_age=settings.session_idle_minutes * 60,
    )
    return response


@router.post("/admin/logout")
def logout(
    request: Request,
    csrf_token: str = Form(...),
    user: AdminUser = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    if not _valid(csrf_token, "admin-csrf:"):
        return RedirectResponse("/admin", status_code=303)
    token = request.cookies.get(get_settings().session_cookie_name, "")
    session = lookup_admin_session(db, token)
    if session:
        revoke_admin_session(db, session)
        log_admin_action(db, str(user.id), "LOGOUT", "admin_session", str(session.id))
        db.commit()
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    return response


@router.get("/admin")
def admin_home(
    request: Request,
    user: AdminUser = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    now = datetime.now(UTC).replace(tzinfo=None)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start.replace(day=today_start.day) + timedelta(days=1)
    total_members = db.scalar(select(func.count(Member.id))) or 0
    total_balance = db.scalar(select(func.coalesce(func.sum(Member.balance), 0))) or 0
    total_cashier = db.scalar(
        select(func.count(Device.id)).where(Device.type == "cashier")
    ) or 0
    total_vending = db.scalar(
        select(func.count(Device.id)).where(Device.type == "vending")
    ) or 0
    transactions_today = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.occurred_at >= today_start,
            Transaction.occurred_at < tomorrow_start,
        )
    ) or 0
    topups_today = db.scalar(
        select(func.coalesce(func.sum(TopUpRequest.amount), 0)).where(
            TopUpRequest.created_at >= today_start,
            TopUpRequest.created_at < tomorrow_start,
            TopUpRequest.status == "COMPLETED",
        )
    ) or 0
    activity = db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(15)
    ).all()
    devices = db.scalars(select(Device).order_by(Device.type, Device.name)).all()
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "user": user,
            "active": "dashboard",
            "csrf_token": _token("admin-csrf:"),
            "total_members": total_members,
            "total_balance": total_balance,
            "total_cashier": total_cashier,
            "total_vending": total_vending,
            "transactions_today": transactions_today,
            "topups_today": topups_today,
            "activity": activity,
            "devices": devices,
        },
    )


@router.get("/admin/settings/password")
def password_page(request: Request, user: AdminUser = Depends(require_admin)):  # noqa: B008
    return templates.TemplateResponse(
        request,
        "admin/password.html",
        {
            "user": user,
            "csrf_token": _token("admin-csrf:"),
            "error": None,
            "active": "settings",
        },
    )


@router.post("/admin/settings/password")
def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
    user: AdminUser = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    if not _valid(csrf_token, "admin-csrf:"):
        return _bad_form(request, "admin/password.html", "Token CSRF tidak valid", 403, user)
    try:
        old_ok = hasher.verify(user.password_hash, old_password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        old_ok = False
    if not old_ok or len(new_password) < 12 or new_password != confirm_password:
        return _bad_form(
            request,
            "admin/password.html",
            "Password lama atau konfirmasi tidak valid",
            400,
            user,
        )
    user.password_hash = hasher.hash(new_password)
    user.must_change_password = False
    count = revoke_other_sessions(db, user, request.state.admin_session)
    log_admin_action(
        db,
        str(user.id),
        "PASSWORD_CHANGED",
        "admin_user",
        str(user.id),
        after={"revoked_sessions": count},
        ip=_ip(request),
    )
    db.commit()
    return RedirectResponse("/admin/settings/password", status_code=303)


@router.get("/admin/settings/sessions")
def sessions_page(
    request: Request,
    user: AdminUser = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    current = request.state.admin_session
    sessions = db.scalars(
        select(AdminSession)
        .where(AdminSession.user_id == user.id, AdminSession.revoked_at.is_(None))
        .order_by(AdminSession.last_seen_at.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/sessions.html",
        {
            "user": user,
            "sessions": sessions,
            "current_session_id": current.id,
            "csrf_token": _token("admin-csrf:"),
            "active": "sessions",
        },
    )


@router.post("/admin/settings/sessions/{session_id}/end")
def end_session(
    session_id: int,
    request: Request,
    csrf_token: str = Form(...),
    user: AdminUser = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    if not _valid(csrf_token, "admin-csrf:"):
        return RedirectResponse("/admin/settings/sessions", status_code=303)
    session = db.scalar(
        select(AdminSession).where(
            AdminSession.id == session_id,
            AdminSession.user_id == user.id,
            AdminSession.revoked_at.is_(None),
        )
    )
    if session and session.id != request.state.admin_session.id:
        revoke_admin_session(db, session)
        log_admin_action(db, str(user.id), "SESSION_ENDED", "admin_session", str(session.id))
        db.commit()
    return RedirectResponse("/admin/settings/sessions", status_code=303)


@router.post("/admin/settings/sessions/end-others")
def end_other_sessions(
    request: Request,
    csrf_token: str = Form(...),
    user: AdminUser = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    if not _valid(csrf_token, "admin-csrf:"):
        return RedirectResponse("/admin/settings/sessions", status_code=303)
    count = revoke_other_sessions(db, user, request.state.admin_session)
    log_admin_action(
        db,
        str(user.id),
        "OTHER_SESSIONS_ENDED",
        "admin_session",
        after={"revoked_sessions": count},
        ip=_ip(request),
    )
    db.commit()
    return RedirectResponse("/admin/settings/sessions", status_code=303)
