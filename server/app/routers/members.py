"""Administrator member list and registration routes."""

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.dependencies.admin import require_admin
from app.models import Member
from app.routers.web import _token, _valid, templates
from app.schemas.member import MemberCreateForm
from app.services.members import create_member

router = APIRouter(prefix="/admin/members", tags=["admin-members"])


def _form_context(user, csrf_token: str, errors: dict, form: dict) -> dict:
    """Build the shared registration form template context."""
    return {
        "user": user,
        "active": "members",
        "csrf_token": csrf_token,
        "errors": errors,
        "form": form,
    }


@router.get("/")
def members_list(
    request: Request,
    q: str | None = None,
    status: str | None = Query(default=None, pattern="^(ACTIVE|SUSPENDED)$"),
    page: int = Query(default=1, ge=1),
    user=Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    """Render the searchable, paginated member list."""
    conditions = []
    search = q.strip() if q else ""
    if search:
        pattern = f"%{search}%"
        conditions.append(
            or_(
                func.lower(Member.full_name).like(f"%{search.lower()}%"),
                Member.member_code.like(pattern),
                Member.phone.like(pattern),
            )
        )
    if status:
        conditions.append(Member.status == status)

    total = db.scalar(select(func.count(Member.id)).where(*conditions)) or 0
    members = db.scalars(
        select(Member)
        .where(*conditions)
        .order_by(Member.id.desc())
        .offset((page - 1) * 20)
        .limit(20)
    ).all()
    total_pages = max(1, (total + 19) // 20)
    return templates.TemplateResponse(
        request,
        "admin/members/list.html",
        {
            "user": user,
            "active": "members",
            "csrf_token": _token("admin-csrf:"),
            "members": members,
            "q": q or "",
            "status": status or "",
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "flash": request.query_params.get("flash"),
        },
    )


@router.get("/new")
def member_form(
    request: Request,
    user=Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    """Render the blank member registration form."""
    return templates.TemplateResponse(
        request,
        "admin/members/form.html",
        _form_context(user, _token("admin-csrf:"), {}, {}),
    )


@router.post("/new")
def create_member_form(
    request: Request,
    full_name: str = Form(...),
    nik: str = Form(...),
    phone: str = Form(...),
    initial_balance: str = Form("0"),
    notes: str | None = Form(None),
    csrf_token: str = Form(...),
    user=Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    """Validate and create a member, preserving submitted values on errors."""
    form = {
        "full_name": full_name,
        "nik": nik,
        "phone": phone,
        "initial_balance": initial_balance,
        "notes": notes or "",
    }
    if not _valid(csrf_token, "admin-csrf:"):
        context = _form_context(
            user, _token("admin-csrf:"), {"csrf_token": "Token CSRF tidak valid"}, form
        )
        return templates.TemplateResponse(
            request, "admin/members/form.html", context, status_code=403
        )

    try:
        data = MemberCreateForm.model_validate(form)
    except Exception as exc:
        errors = {}
        if hasattr(exc, "errors"):
            for error in exc.errors():
                field = str(error["loc"][0])
                errors[field] = error["msg"]
        context = _form_context(user, _token("admin-csrf:"), errors, form)
        return templates.TemplateResponse(
            request, "admin/members/form.html", context, status_code=422
        )

    try:
        create_member(db, data, actor="admin")
        db.commit()
    except ValueError as exc:
        db.rollback()
        context = _form_context(user, _token("admin-csrf:"), {"nik": str(exc)}, form)
        return templates.TemplateResponse(
            request, "admin/members/form.html", context, status_code=409
        )

    return RedirectResponse(
        "/admin/members?flash=Member%20berhasil%20dibuat",
        status_code=303,
    )
