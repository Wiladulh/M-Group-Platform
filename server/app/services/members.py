"""Member registration service with encrypted NIK and keyed duplicate detection."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Card, Device, Member, Transaction
from app.security.encryption import blind_index_nik, decrypt_nik, encrypt_nik
from app.services.audit import log_admin_action
from app.services.cache_version import bump_member_cache_version


def _next_member_code(session: Session) -> str:
    """Allocate the next sequential MG-[A-Z]NNNNN member code."""
    last_code = session.scalar(
        select(Member.member_code).order_by(Member.member_code.desc()).limit(1)
    )
    if last_code is None:
        return "MG-A00001"
    letter = last_code[3]
    number = int(last_code[4:])
    if number < 99999:
        number += 1
    else:
        if letter == "Z":
            raise ValueError("Kapasitas kode member telah habis")
        letter = chr(ord(letter) + 1)
        number = 1
    return f"MG-{letter}{number:05d}"


def create_member(session: Session, data, actor: str = "admin") -> Member:
    """Create a member after checking the NIK blind index for duplicates."""
    nik = data.nik.strip()
    nik_idx = blind_index_nik(nik)
    duplicate = session.scalar(select(Member.id).where(Member.nik_idx == nik_idx))
    if duplicate is not None:
        raise ValueError("NIK sudah terdaftar")

    member = Member(
        member_code=_next_member_code(session),
        full_name=data.full_name.strip(),
        nik_enc=encrypt_nik(nik),
        nik_idx=nik_idx,
        phone=data.phone,
        balance=data.initial_balance,
        notes=data.notes,
    )
    session.add(member)
    session.flush()
    log_admin_action(
        session,
        actor,
        "MEMBER_CREATED",
        "member",
        str(member.id),
        after={
            "member_code": member.member_code,
            "full_name": member.full_name,
            "initial_balance": member.balance,
        },
    )
    return member


def get_member_or_none(session: Session, member_id: int) -> Member | None:
    """Return the member with the given id, or None when it does not exist."""
    return session.get(Member, member_id)


def update_member_profile(session: Session, member: Member, data, actor: str = "admin") -> Member:
    """Update profile fields; NIK changes are re-indexed and audited without the value."""
    before = {
        "full_name": member.full_name,
        "phone": member.phone,
        "notes": member.notes,
    }
    changed_nik = False
    if data.nik is not None:
        new_idx = blind_index_nik(data.nik)
        if new_idx != member.nik_idx:
            duplicate = session.scalar(
                select(Member.id).where(Member.nik_idx == new_idx, Member.id != member.id)
            )
            if duplicate is not None:
                raise ValueError("NIK sudah terdaftar")
            member.nik_enc = encrypt_nik(data.nik)
            member.nik_idx = new_idx
            changed_nik = True

    member.full_name = data.full_name.strip()
    member.phone = data.phone
    member.notes = data.notes
    session.flush()

    after = {
        "full_name": member.full_name,
        "phone": member.phone,
        "notes": member.notes,
    }
    if changed_nik:
        after["nik"] = "NIK diubah"
        before["nik"] = "(tersembunyi)"
    log_admin_action(
        session,
        actor,
        "MEMBER_UPDATED",
        "member",
        str(member.id),
        before=before,
        after=after,
    )
    return member


def change_member_status(
    session: Session, member: Member, status: str, reason: str, actor: str = "admin"
) -> Member:
    """Activate or suspend a member; suspension bumps the cache version so units drop the member."""
    previous = member.status
    member.status = status
    session.flush()
    if previous != status:
        bump_member_cache_version(session, member.id)
    log_admin_action(
        session,
        actor,
        "MEMBER_STATUS_CHANGED",
        "member",
        str(member.id),
        before={"status": previous},
        after={"status": status, "reason": reason},
    )
    return member


def reveal_nik(session: Session, member: Member, actor: str = "admin") -> str:
    """Decrypt the NIK for display and record the reveal in the audit log."""
    plain = decrypt_nik(member.nik_enc)
    log_admin_action(
        session,
        actor,
        "MEMBER_NIK_REVEALED",
        "member",
        str(member.id),
    )
    return plain


def member_detail_summary(session: Session, member: Member) -> dict:
    """Collect card history and finance totals for the member detail page (spec 14.7 B-D)."""
    cards = session.scalars(
        select(Card).where(Card.member_id == member.id).order_by(Card.id.desc())
    ).all()
    total_topup = session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.member_id == member.id,
            Transaction.type == "TOPUP",
            Transaction.status == "COMPLETED",
        )
    )
    payments = session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.member_id == member.id,
            Transaction.type == "PAYMENT",
            Transaction.status == "COMPLETED",
        )
    )
    refunds = session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.member_id == member.id,
            Transaction.type == "REFUND",
            Transaction.status == "COMPLETED",
        )
    )
    history = session.execute(
        select(Transaction, Device.name, Device.device_id)
        .outerjoin(Device, Device.id == Transaction.device_id)
        .where(Transaction.member_id == member.id)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        .limit(50)
    ).all()
    return {
        "cards": cards,
        "active_card": next((c for c in cards if c.status in ("ACTIVE", "LOCKED")), None),
        "total_topup": int(total_topup or 0),
        "total_spending": int((payments or 0) - (refunds or 0)),
        "history": history,
    }
