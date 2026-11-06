"""Admin top-up creation and reversal service; no WebUI/session dependency."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import AdminUser, AuditLog, Member, TopUpRequest, Transaction
from app.services.allowance import assert_can_spend_online
from app.services.ledger import InsufficientBalance, LedgerError, LedgerService
from app.services.topup import _validate_amount


class AdminTopupService:
    """Compose admin top-up operations into atomic ledger and audit transactions."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.ledger = LedgerService(session)

    def create_topup(
        self,
        member_id: int,
        amount: int,
        *,
        request_uuid: str,
        note: str | None,
        performed_by_admin_id: int,
        ip: str | None,
    ) -> TopUpRequest:
        """Credit an active member and persist the matching top-up request."""
        with self.session.begin():
            _validate_amount(self.session, amount)
            admin = self.session.get(AdminUser, performed_by_admin_id)
            if admin is None:
                raise DomainError(
                    code="VALIDATION_ERROR",
                    status_code=422,
                    details={"detail": "Admin tidak ditemukan"},
                )
            member = self.session.get(Member, member_id)
            if member is None or member.status != "ACTIVE":
                raise DomainError(code="MEMBER_SUSPENDED", status_code=422)

            existing = self.session.scalar(
                select(TopUpRequest).where(TopUpRequest.request_uuid == request_uuid)
            )
            if existing is not None:
                same = (
                    existing.member_id == member_id
                    and existing.amount == amount
                    and existing.source == "WEBUI"
                    and existing.processed_by_type == "ADMIN"
                    and existing.processed_by_id == str(performed_by_admin_id)
                    and existing.note == note
                )
                if same:
                    return existing
                raise DomainError(code="DUPLICATE_TXN", status_code=409)

            before = member.balance
            txn = self.ledger._credit_internal(
                member_id=member_id,
                amount=amount,
                txn_uuid=request_uuid,
                type="TOPUP",
                source="ADMIN",
                performed_by_type="ADMIN",
                performed_by_id=str(performed_by_admin_id),
                note=note,
            )
            row = TopUpRequest(
                request_uuid=request_uuid,
                member_id=member_id,
                amount=amount,
                status="COMPLETED",
                source="WEBUI",
                device_id=None,
                processed_by_type="ADMIN",
                processed_by_id=str(performed_by_admin_id),
                txn_id=txn.id,
                note=note,
            )
            self.session.add(row)
            self.session.flush()
            self.session.add(
                AuditLog(
                    actor_type="ADMIN",
                    actor_id=str(performed_by_admin_id),
                    action="topup.admin",
                    entity="topup_request",
                    entity_id=str(row.id),
                    before_json=json.dumps({"member_balance": before}, separators=(",", ":")),
                    after_json=json.dumps(
                        {"member_balance": txn.balance_after}, separators=(",", ":")
                    ),
                    ip=ip,
                )
            )
            return row

    def reverse_topup(
        self,
        topup_request_id: int,
        *,
        reason: str,
        performed_by_admin_id: int,
        ip: str | None,
    ) -> TopUpRequest:
        """Reverse a completed top-up without mutating the original ledger row."""
        if not isinstance(reason, str) or not reason.strip():
            raise DomainError(
                code="VALIDATION_ERROR",
                status_code=400,
                details={"detail": "Alasan pembatalan wajib diisi"},
            )
        reason = reason.strip()
        try:
            with self.session.begin():
                admin = self.session.get(AdminUser, performed_by_admin_id)
                if admin is None:
                    raise DomainError(
                        code="VALIDATION_ERROR",
                        status_code=422,
                        details={"detail": "Admin tidak ditemukan"},
                    )
                row = self.session.get(TopUpRequest, topup_request_id)
                if row is None or row.status != "COMPLETED":
                    raise DomainError(
                        code="VALIDATION_ERROR",
                        status_code=422,
                        details={"detail": "Top-up tidak dapat dibatalkan"},
                    )
                original = self.session.get(Transaction, row.txn_id)
                if original is None or original.type != "TOPUP" or original.direction != "CREDIT":
                    raise DomainError(
                        code="VALIDATION_ERROR",
                        status_code=422,
                        details={"detail": "Transaksi top-up tidak valid"},
                    )
                if (
                    self.session.scalar(
                        select(Transaction.id).where(Transaction.ref_txn_id == original.id)
                    )
                    is not None
                ):
                    raise DomainError(
                        code="VALIDATION_ERROR",
                        status_code=422,
                        details={"detail": "Top-up sudah dibatalkan"},
                    )
                member = self.session.get(Member, row.member_id)
                if member is None or member.balance < row.amount:
                    raise DomainError(
                        code="REVERSE_INSUFFICIENT",
                        status_code=422,
                    )
                assert_can_spend_online(self.session, row.member_id, row.amount)
                before = {"status": row.status, "reason": None}
                reversal = self.ledger._reverse_internal(
                    original.id,
                    reason=reason,
                    performed_by_type="ADMIN",
                    performed_by_id=str(performed_by_admin_id),
                )
                row.status = "REVERSED"
                row.reversal_txn_id = reversal.id
                row.reverse_reason = reason
                self.session.flush()
                self.session.add(
                    AuditLog(
                        actor_type="ADMIN",
                        actor_id=str(performed_by_admin_id),
                        action="topup.reverse",
                        entity="topup_request",
                        entity_id=str(row.id),
                        before_json=json.dumps(before, separators=(",", ":")),
                        after_json=json.dumps(
                            {"status": row.status, "reason": reason},
                            separators=(",", ":"),
                        ),
                        ip=ip,
                    )
                )
                return row
        except InsufficientBalance as exc:
            raise DomainError(code="REVERSE_INSUFFICIENT", status_code=422) from exc
        except LedgerError as exc:
            raise DomainError(
                code="VALIDATION_ERROR",
                status_code=422,
                details={"detail": "Top-up tidak dapat dibatalkan"},
            ) from exc
