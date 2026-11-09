"""Regression guard for BALANCE_STATUSES against spec §5."""

from app.cli import BALANCE_STATUSES
from app.models.txn import Transaction

TRANSACTION_STATUSES = {
    "COMPLETED",
    "PENDING_DISPENSE",
    "DISPENSE_FAILED",
    "REVERSED",
    "REJECTED",
}


def test_balance_statuses_subset_of_transaction_statuses():
    """Every balance-affecting status must be a documented valid status."""
    for status in BALANCE_STATUSES:
        assert status in TRANSACTION_STATUSES, (
            f"BALANCE_STATUSES contains '{status}' which is not a valid "
            f"Transaction status per spec §5. Valid: {sorted(TRANSACTION_STATUSES)}. "
            "If a new status is added to the model, update the model constraint, "
            "this test's TRANSACTION_STATUSES set, and (if balance-affecting) "
            "BALANCE_STATUSES together."
        )


def test_refunded_not_in_balance_statuses():
    """Regression guard: REFUNDED must never appear in BALANCE_STATUSES."""
    assert "REFUNDED" not in BALANCE_STATUSES, (
        "REFUNDED was removed in P13-FIX1 (refunds are separate REFUND "
        "ledger rows, not a payment status). Do not re-add it. "
        "See docs/ASSUMPTIONS.md A-P13-FIX1-01."
    )


def test_transaction_model_importable():
    """Sanity: Transaction model is importable and has expected statuses covered.

    This test does NOT read constraint from Transaction; it only verifies
    that the module import works and that the model class exists. The
    hardcoded TRANSACTION_STATUSES set above remains the source of truth
    for spec §5 statuses until P15+ refactor reads the constraint directly.
    """
    assert Transaction is not None
