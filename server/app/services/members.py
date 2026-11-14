"""Member registration service with encrypted NIK and keyed duplicate detection."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Member
from app.security.encryption import blind_index_nik, encrypt_nik
from app.services.audit import log_admin_action


def _next_member_code(session: Session) -> str:
    """Allocate the next sequential MG-[A-Z]NNNNN member code."""
    last_code = session.scalar(select(Member.member_code).order_by(Member.member_code.desc()).limit(1))
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
