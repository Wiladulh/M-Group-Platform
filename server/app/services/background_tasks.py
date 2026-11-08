"""Periodic automatic refunds for vending transactions left pending dispense."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import db
from app.models import Transaction
from app.services.ledger import LedgerError, LedgerService

logger = logging.getLogger(__name__)

PENDING_DISPENSE_REFUND_AFTER = timedelta(minutes=2)
PENDING_DISPENSE_MONITOR_INTERVAL_S = 30


async def pending_dispense_monitor_once() -> int:
    """Refund stale pending transactions once; return the number refunded."""
    cutoff = datetime.now(UTC) - PENDING_DISPENSE_REFUND_AFTER
    with db.SessionLocal() as session:
        stale_rows = session.execute(
            select(
                Transaction.id,
                Transaction.txn_uuid,
                Transaction.member_id,
                Transaction.amount,
            ).where(
                Transaction.status == "PENDING_DISPENSE",
                Transaction.created_at < cutoff,
            )
        ).all()

    refunded = 0
    for txn_id, txn_uuid, member_id, amount in stale_rows:
        try:
            with db.SessionLocal() as session:
                refund = LedgerService(session).fail_pending_dispense(txn_id, auto_refund=True)
                logger.info(
                    "pending_dispense_auto_refunded txn_uuid=%s member_id=%s amount=%s refund_txn_id=%s",
                    txn_uuid,
                    member_id,
                    amount,
                    refund.id,
                )
                refunded += 1
        except LedgerError:
            logger.warning("pending_dispense_refund_skipped txn_id=%s", txn_id, exc_info=True)
        except Exception:
            logger.exception("pending_dispense_refund_failed txn_id=%s", txn_id)
    return refunded


async def pending_dispense_monitor_loop(application) -> None:
    """Run the stale dispense refund monitor until application shutdown."""
    while True:
        try:
            await pending_dispense_monitor_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pending_dispense_monitor_cycle_failed")
        finally:
            task = asyncio.current_task()
            if task is not None and not task.cancelling():
                await asyncio.sleep(PENDING_DISPENSE_MONITOR_INTERVAL_S)
