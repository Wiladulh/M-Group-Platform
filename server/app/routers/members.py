"""Administrator member list and registration routes."""

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.dependencies.admin import require_admin
from app.models import Member
from app.routers.web import _token, _valid, templates
from app.schemas.member import MemberCreateForm, MemberEditForm, MemberStatusForm
from app.services.members import (
    change_member_status,
    get_member_or_none,
    member_detail_summary,
    reveal_nik,
    update_member_profile,
)
from app.services.members import create_member as _create_member

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


@router.get("")
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
    full_name: str | None = Form(None),
    nik: str | None = Form(None),
    phone: str | None = Form(None),
    initial_balance: str | None = Form("0"),
    notes: str | None = Form(None),
    csrf_token: str | None = Form(None),
    user=Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    """Validate and create a member, preserving submitted values on errors."""
    form = {
        "full_name": full_name or "",
        "nik": nik or "",
        "phone": phone or "",
        "initial_balance": initial_balance or "0",
        "notes": notes or "",
    }
    if not csrf_token or not _valid(csrf_token, "admin-csrf:"):
        context = _form_context(
            user, _token("admin-csrf:"), {"csrf_token": "Token CSRF tidak valid"}, form
        )
        return templates.TemplateResponse(
            request, "admin/members/form.html", context, status_code=403
        )

    try:
        data = MemberCreateForm.model_validate(form)
    except ValidationError as exc:
        errors = {}
        for error in exc.errors():
            field = str(error["loc"][0])
            errors[field] = error["msg"]
        context = _form_context(user, _token("admin-csrf:"), errors, form)
        return templates.TemplateResponse(
            request, "admin/members/form.html", context, status_code=422
        )

    try:
        _create_member(db, data, actor="admin")
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


def _member_or_404(db: Session, member_id: int):
    """Return the member or raise 404 so unknown ids never render a page."""
    member = get_member_or_none(db, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member tidak ditemukan")
    return member


def _detail_context(
    db: Session, user, member, flash: str | None = None, revealed: str | None = None
) -> dict:
    """Build the member detail template context with a fresh CSRF token."""
    summary = member_detail_summary(db, member)
    return {
        "user": user,
        "active": "members",
        "csrf_token": _token("admin-csrf:"),
        "member": member,
        "summary": summary,
        "flash": flash,
        "revealed_nik": revealed,
    }


@router.get("/{member_id}")
def member_detail(
    request: Request,
    member_id: int,
    user=Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    """Render the member detail page: identity, card, finance, and activity."""
    member = _member_or_404(db, member_id)
    return templates.TemplateResponse(
        request,
        "admin/members/detail.html",
        _detail_context(db, user, member, flash=request.query_params.get("flash")),
    )


@router.get("/{member_id}/edit")
def member_edit_form(
    request: Request,
    member_id: int,
    user=Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    """Render the edit form; the NIK is never prefilled (masked elsewhere)."""
    member = _member_or_404(db, member_id)
    form = {
        "full_name": member.full_name,
        "phone": member.phone or "",
        "notes": member.notes or "",
    }
    return templates.TemplateResponse(
        request,
        "admin/members/edit.html",
        {**_form_context(user, _token("admin-csrf:"), {}, form), "member": member},
    )


@router.post("/{member_id}/edit")
def member_edit_submit(
    request: Request,
    member_id: int,
    full_name: str | None = Form(None),
    nik: str | None = Form(None),
    phone: str | None = Form(None),
    notes: str | None = Form(None),
    csrf_token: str | None = Form(None),
    user=Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    """Validate and save profile edits; NIK changes are optional and audited."""
    member = _member_or_404(db, member_id)
    form = {"full_name": full_name or "", "phone": phone or "", "notes": notes or ""}
    template = "admin/members/edit.html"
    context_base = {"member": member}
    if not csrf_token or not _valid(csrf_token, "admin-csrf:"):
        context = {
            **_form_context(
                user, _token("admin-csrf:"), {"csrf_token": "Token CSRF tidak valid"}, form
            ),
            **context_base,
        }
        return templates.TemplateResponse(request, template, context, status_code=403)

    try:
        data = MemberEditForm.model_validate({**form, "nik": nik})
    except ValidationError as exc:
        errors = {str(error["loc"][0]): error["msg"] for error in exc.errors()}
        context = {**_form_context(user, _token("admin-csrf:"), errors, form), **context_base}
        return templates.TemplateResponse(request, template, context, status_code=422)

    try:
        update_member_profile(db, member, data, actor="admin")
        db.commit()
    except ValueError as exc:
        db.rollback()
        context = {
            **_form_context(user, _token("admin-csrf:"), {"nik": str(exc)}, form),
            **context_base,
        }
        return templates.TemplateResponse(request, template, context, status_code=409)

    return RedirectResponse(
        f"/admin/members/{member_id}?flash=Data%20member%20berhasil%20diperbarui",
        status_code=303,
    )


@router.post("/{member_id}/status")
def member_status_submit(
    request: Request,
    member_id: int,
    status: str = Form(...),
    reason: str | None = Form(None),
    csrf_token: str | None = Form(None),
    user=Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    """Activate or suspend a member with a mandatory reason."""
    member = _member_or_404(db, member_id)
    if not csrf_token or not _valid(csrf_token, "admin-csrf:"):
        raise HTTPException(status_code=403, detail="Token CSRF tidak valid")
    try:
        data = MemberStatusForm.model_validate({"status": status, "reason": reason or ""})
    except ValidationError:
        return RedirectResponse(
            f"/admin/members/{member_id}?flash=Alasan%20wajib%20diisi",
            status_code=303,
        )
    change_member_status(db, member, data.status, data.reason, actor="admin")
    db.commit()
    label = "diaktifkan" if data.status == "ACTIVE" else "dinonaktifkan"
    return RedirectResponse(
        f"/admin/members/{member_id}?flash=Member%20{label}",
        status_code=303,
    )


@router.post("/{member_id}/reveal-nik")
def member_reveal_nik(
    request: Request,
    member_id: int,
    csrf_token: str = Form(...),
    user=Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_session),  # noqa: B008
):
    """Show the full NIK once on the detail page and record the reveal in audit."""
    member = _member_or_404(db, member_id)
    if not _valid(csrf_token, "admin-csrf:"):
        raise HTTPException(status_code=403, detail="Token CSRF tidak valid")
    plain = reveal_nik(db, member, actor="admin")
    db.commit()
    return templates.TemplateResponse(
        request,
        "admin/members/detail.html",
        _detail_context(db, user, member, revealed=plain),
    )
