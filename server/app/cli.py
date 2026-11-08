"""Maintenance and development seed command-line utilities."""

import argparse
import os
import sys
from collections.abc import Callable
from typing import TextIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal
from app.models import AdminUser, Device, Member, Transaction
from app.security.device_token import generate_device_token, hash_device_token
from app.security.passwords import hash_password, validate_admin_password

BALANCE_STATUSES = (
    "COMPLETED",
    "PENDING_DISPENSE",
    "DISPENSE_FAILED",
    "REFUNDED",
    "REVERSED",
)

DEVICE_SEEDS = (
    ("CSH-001", "Cashier 001", "cashier", "manual", 0),
    ("VND-001", "Vending 001", "vending", "vending", 5),
    ("VND-002", "Vending 002", "vending", "vending", 5),
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


def seed_minimal(
    session_factory: Callable[[], Session] | sessionmaker | None = None,
    environ: dict[str, str] | None = None,
    output: TextIO | None = None,
) -> int:
    """Create one admin and three development devices without overwriting rows."""
    env = os.environ if environ is None else environ
    username = env.get("ADMIN_USERNAME", "").strip()
    password = env.get("ADMIN_PASSWORD", "")
    if not username or not password:
        print("ERROR: ADMIN_USERNAME and ADMIN_PASSWORD are required.", file=output or sys.stderr)
        return 2
    try:
        validate_admin_password(password, username, None)
    except ValueError as exc:
        print(f"ERROR: invalid ADMIN_PASSWORD: {exc}", file=output or sys.stderr)
        return 2

    factory = session_factory or SessionLocal
    stream = output or sys.stdout
    printed_keys: list[tuple[str, str]] = []
    with factory() as session:
        if session.scalar(select(AdminUser).limit(1)) is None:
            session.add(
                AdminUser(
                    username=username,
                    display_name=username,
                    password_hash=hash_password(password),
                    must_change_password=True,
                )
            )
            session.flush()

        for device_id, name, device_type, mode, slot_count in DEVICE_SEEDS:
            if session.scalar(select(Device.id).where(Device.device_id == device_id)) is not None:
                continue
            token = generate_device_token()
            session.add(
                Device(
                    device_id=device_id,
                    name=name,
                    type=device_type,
                    reported_mode=mode,
                    slot_count=slot_count,
                    token_hash=hash_device_token(token),
                    status="ACTIVE",
                    config_json='{"offline_enabled":true}',
                )
            )
            printed_keys.append((device_id, token))
        session.commit()

    if printed_keys:
        print(
            "WARNING: Device Keys are shown ONCE. Copy them to secure provisioning storage; "
            "they cannot be retrieved from the database.",
            file=stream,
        )
        for device_id, token in printed_keys:
            print(f"{device_id} Device Key: {token}", file=stream)
    else:
        print("No new devices created; existing device keys were not displayed.", file=stream)
    print(
        "seed-minimal complete. Development database only; do not run against production.",
        file=stream,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify-ledger", help="Verify member balances against ledger rows")
    subparsers.add_parser("seed-minimal", help="Seed one admin and three development devices")
    subparsers.add_parser(
        "reset-admin-password",
        help="Reset the single Admin password (implemented in P14)",
    )
    args = parser.parse_args()
    if args.command == "verify-ledger":
        return verify_ledger()
    if args.command == "seed-minimal":
        return seed_minimal()
    if args.command == "reset-admin-password":
        print("Not yet implemented (P14)")
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
