"""Maintenance command-line utilities for M-Group Platform."""

import argparse
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Member, Transaction


BALANCE_STATUSES = (
    "COMPLETED",
    "PENDING_DISPENSE",
    "DISPENSE_FAILED",
    "REVERSED",
)


def verify_ledger() -> int:
    """Compare every stored member balance with the append-only ledger sum."""
    mismatches: list[tuple[str, int, int, int, int]] = []
    verified = 0
    with SessionLocal() as session:
        members = session.scalars(select(Member).order_by(Member.id)).all()
        for member in members:
            sum_credit = session.scalar(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.member_id == member.id,
                    Transaction.direction == "CREDIT",
                    Transaction.status.in_(BALANCE_STATUSES),
                )
            )
            sum_debit = session.scalar(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    Transaction.member_id == member.id,
                    Transaction.direction == "DEBIT",
                    Transaction.status.in_(BALANCE_STATUSES),
                )
            )
            expected = int(sum_credit) - int(sum_debit)
            if member.balance != expected:
                mismatches.append(
                    (member.member_code, member.balance, expected, int(sum_credit), int(sum_debit))
                )
            else:
                verified += 1

    if mismatches:
        for code, actual, expected, credits, debits in mismatches:
            print(
                f"MISMATCH {code}: balance={actual}, expected={expected}, "
                f"credits={credits}, debits={debits}"
            )
        print(f"FAIL: {len(mismatches)} mismatches")
        return 1
    print(f"OK: {verified} members verified")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-ledger", help="Verify member balances against ledger rows")
    subparsers.add_parser(
        "reset-admin-password",
        help="Reset the single Admin password (implemented in P14)",
    )
    args = parser.parse_args()
    if args.command == "verify-ledger":
        return verify_ledger()
    if args.command == "reset-admin-password":
        print("Not yet implemented (P14)")
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
