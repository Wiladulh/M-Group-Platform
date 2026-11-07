"""Transactional remote card binding and PIN-only recovery state machine."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import DomainError
from app.models import Card, CardBindSession, Member, OfflineAllowance
from app.security.offline_pin import compute_offline_verifier, generate_salt
from app.security.pins import hash_pin, validate_pin_format
from app.services.allowance import AllowanceService
from app.services.events import CacheInvalidateEvent, CacheUpdateEvent, CardStatusChangedEvent

ACTIVE_STATES = ("WAITING_DEVICE", "WAITING_CARD", "WAITING_PIN", "CONFIRM_PIN")
BIND_MODES = ("NEW_CARD", "REPLACE_CARD", "PIN_ONLY")


def _candidate_hash(pin: str) -> str:
    pepper = Settings().pin_pepper.get_secret_value().encode()
    return hmac.new(pepper, pin.encode(), hashlib.sha256).hexdigest()


def _raise(code: str, message: str, *, details: dict | None = None) -> DomainError:
    status_code = 409 if code == "BIND_CONFLICT" else 400
    return DomainError(message, details=details, code=code, status_code=status_code)


class BindingService:
    """Session-bound card binding service; caller controls transaction boundaries."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _get_session(self, session_uuid: str) -> CardBindSession:
        row = self.session.scalar(
            select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
        )
        if row is None:
            raise _raise("BIND_FAILED", "Sesi binding tidak ditemukan")
        return row

    def _fail(self, row: CardBindSession, reason: str) -> None:
        row.state = "FAILED"
        row.failure_reason = reason
        self.session.flush()

    def create_session(
        self,
        member_id: int,
        device_id: int,
        mode: str,
        created_by_admin_id: int,
    ) -> CardBindSession:
        if mode not in BIND_MODES:
            raise _raise("VALIDATION_ERROR", "Mode binding tidak valid")
        member = self.session.get(Member, member_id)
        if member is None or member.status != "ACTIVE":
            raise _raise("BIND_FAILED", "Member tidak ditemukan atau tidak aktif")
        active = self.session.scalar(
            select(CardBindSession).where(
                CardBindSession.state.in_(ACTIVE_STATES),
                (CardBindSession.device_id == device_id)
                | (CardBindSession.member_id == member_id),
            )
        )
        if active is not None:
            raise _raise(
                "BIND_CONFLICT",
                "Sudah ada sesi binding aktif untuk perangkat atau member ini",
                details={"session_uuid": active.session_uuid},
            )
        row = CardBindSession(
            session_uuid=str(uuid4()),
            member_id=member_id,
            device_id=device_id,
            mode=mode,
            state="WAITING_DEVICE",
            expires_at=datetime.now(UTC) + timedelta(seconds=90),
            created_by_admin_id=created_by_admin_id,
            pin_attempts=0,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def expire_session(self, session_uuid: str) -> CardBindSession:
        row = self._get_session(session_uuid)
        if row.state in ACTIVE_STATES:
            row.state = "EXPIRED"
            row.failure_reason = "expired"
            row.pin_candidate_hash = None
            self.session.flush()
        return row

    def cancel_session(self, session_uuid: str, actor_type: str = "ADMIN") -> CardBindSession:
        row = self._get_session(session_uuid)
        if row.state in ACTIVE_STATES:
            row.state = "CANCELLED"
            row.failure_reason = f"cancelled_by_{actor_type.lower()}"
            row.pin_candidate_hash = None
            self.session.flush()
        return row

    def on_card_scanned(
        self, session_uuid: str, uid: str, hw_ts_utc: datetime
    ) -> CardBindSession:
        row = self._get_session(session_uuid)
        if row.state not in {"WAITING_CARD", "WAITING_DEVICE"}:
            raise _raise("BIND_FAILED", "Sesi tidak sedang menunggu kartu")
        normalized_uid = uid.strip().upper()
        if (
            len(normalized_uid) not in {8, 14, 20}
            or any(char not in "0123456789ABCDEF" for char in normalized_uid)
        ):
            self._fail(row, "UID kartu tidak valid")
            raise _raise("VALIDATION_ERROR", "UID kartu tidak valid")

        card = self.session.scalar(select(Card).where(Card.uid == normalized_uid))
        if row.mode in {"NEW_CARD", "REPLACE_CARD"}:
            if card is not None:
                self._fail(row, "UID sudah terdaftar")
                raise _raise("BIND_CONFLICT", "Kartu sudah terdaftar pada member lain")
            existing = self.session.scalar(
                select(Card.id).where(
                    Card.member_id == row.member_id,
                    Card.status.in_(("ACTIVE", "LOCKED")),
                )
            )
            if row.mode == "NEW_CARD" and existing is not None:
                self._fail(row, "Member sudah memiliki kartu aktif")
                raise _raise("BIND_CONFLICT", "Member sudah memiliki kartu aktif")
            if row.mode == "REPLACE_CARD" and existing is None:
                self._fail(row, "Kartu lama tidak ditemukan")
                raise _raise("BIND_FAILED", "Kartu lama tidak ditemukan")
        else:
            if card is None:
                self._fail(row, "Kartu tidak terdaftar")
                raise _raise("CARD_UNKNOWN", "Kartu tidak terdaftar")
            if card.member_id != row.member_id:
                self._fail(row, "Kartu milik member lain")
                raise _raise("BIND_CONFLICT", "Kartu sudah terdaftar pada member lain")
            if card.status not in {"ACTIVE", "LOCKED"}:
                self._fail(row, "Kartu tidak dapat digunakan untuk PIN_ONLY")
                raise _raise("CARD_UNKNOWN", "Kartu tidak terdaftar")

        row.uid_scanned = normalized_uid
        row.state = "WAITING_PIN"
        row.failure_reason = None
        self.session.flush()
        return row

    def on_pin_submitted(
        self, session_uuid: str, pin: str, pin_confirm: str | None
    ) -> CardBindSession:
        row = self._get_session(session_uuid)
        if row.state not in {"WAITING_PIN", "CONFIRM_PIN"}:
            raise _raise("BIND_FAILED", "Sesi tidak sedang menunggu PIN")
        if not isinstance(pin, str) or not pin.isascii() or not pin.isdigit():
            raise _raise("VALIDATION_ERROR", "PIN harus terdiri dari tepat 4 digit angka")
        row.state = "CONFIRM_PIN"
        row.pin_candidate_hash = _candidate_hash(pin)
        if pin_confirm is None:
            self.session.flush()
            return row
        if not isinstance(pin_confirm, str) or not hmac.compare_digest(
            row.pin_candidate_hash, _candidate_hash(pin_confirm)
        ):
            row.pin_attempts += 1
            if row.pin_attempts >= 3:
                row.state = "FAILED"
                row.failure_reason = "PIN tidak cocok 3 kali"
                row.pin_candidate_hash = None
                self.session.flush()
                raise _raise("BIND_FAILED", "PIN tidak cocok 3 kali")
            self.session.flush()
            raise _raise("VALIDATION_ERROR", "PIN tidak cocok. Silakan ulangi")

        try:
            validate_pin_format(pin)
        except ValueError as exc:
            self.session.flush()
            raise _raise("VALIDATION_ERROR", str(exc)) from exc

        now = datetime.now(UTC)
        salt = generate_salt()
        pin_hash = hash_pin(pin)
        offline_verifier = compute_offline_verifier(pin, salt).hex()
        member = self.session.get(Member, row.member_id)
        if member is None:
            raise _raise("BIND_FAILED", "Member tidak ditemukan")

        if row.mode == "PIN_ONLY":
            card = self.session.scalar(
                select(Card).where(Card.uid == row.uid_scanned, Card.member_id == row.member_id)
            )
            if card is None:
                raise _raise("CARD_UNKNOWN", "Kartu tidak terdaftar")
            card.pin_hash = pin_hash
            card.offline_verifier = offline_verifier
            card.offline_salt = salt.hex()
            card.pin_fail_count = 0
            card.status = "ACTIVE"
            card.bound_at = now
            card.bound_by_device_id = row.device_id
            card.deactivated_reason = None
            AllowanceService(self.session).apply_allowances(member.id)
        else:
            old_uids = []
            if row.mode == "REPLACE_CARD":
                old_cards = self.session.scalars(
                    select(Card).where(
                        Card.member_id == row.member_id,
                        Card.status.in_(("ACTIVE", "LOCKED")),
                    )
                ).all()
                for old_card in old_cards:
                    old_uids.append(old_card.uid)
                    old_card.status = "REPLACED"
                    old_card.deactivated_reason = "card_replaced"
                self.session.flush()
                self.session.execute(
                    delete(OfflineAllowance).where(OfflineAllowance.member_id == row.member_id)
                )
            card = Card(
                member_id=row.member_id,
                uid=row.uid_scanned,
                pin_hash=pin_hash,
                offline_verifier=offline_verifier,
                offline_salt=salt.hex(),
                pin_fail_count=0,
                status="ACTIVE",
                bound_at=now,
                bound_by_device_id=row.device_id,
            )
            self.session.add(card)
            self.session.flush()
            if old_uids:
                self.session.info.setdefault("mgt_pending_events", []).append(
                    CacheInvalidateEvent(uid_list=old_uids, all=False)
                )
                self.session.info.setdefault("mgt_pending_events", []).append(
                    CacheUpdateEvent(
                        member_id=member.id,
                        uid_list=[card.uid],
                        balance_snapshot=member.balance,
                        offline_allowance={},
                        card_status="ACTIVE",
                        computed_at_utc=now.isoformat().replace("+00:00", "Z"),
                    )
                )
            else:
                AllowanceService(self.session).apply_allowances(member.id)

        row.state = "DONE"
        row.failure_reason = None
        row.pin_attempts = 0
        row.pin_candidate_hash = None
        self.session.info.setdefault("mgt_pending_events", []).append(
            CardStatusChangedEvent(uid=card.uid, status="ACTIVE")
        )
        self.session.flush()
        return row

    def on_device_cancel(self, session_uuid: str) -> CardBindSession:
        return self.cancel_session(session_uuid, actor_type="DEVICE")
