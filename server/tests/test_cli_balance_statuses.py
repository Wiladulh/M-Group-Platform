"""Regression guard: BALANCE_STATUSES must not contain REFUNDED.

Context: P13-FIX1 reverted the `REFUNDED` transaction status. Refunds are
now separate `REFUND` ledger rows, not a status on the payment transaction.
`cli.py` retained a stale `REFUNDED` entry in `BALANCE_STATUSES`, which
caused `verify-ledger` to include a status that cannot exist in the model.

This test is a MINIMAL REGRESSION GUARD. It hardcodes the expected valid
status set instead of reading it from the Transaction model constraint.
A future improvement (P15+) should read the constraint directly from the
model (e.g. `Transaction.__table__.constraints` or `Transaction.status.type.enums`)
so this test stays in sync if new statuses are added.

See: docs/ASSUMPTIONS.md A-P13-FIX1-01.
"""

from app.cli import BALANCE_STATUSES


# Expected valid Transaction.status values per spec §5 and P13-FIX1.
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
