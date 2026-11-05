"""Minimum viable offline allowance tests for P4."""

import json

import pytest

from app.models import Base, Device, Member, OfflineAllowance, Setting
from app.services.allowance import AllowanceService
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def allowance_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'allowance.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def seed_member(session, balance=30_000):
    member = Member(
        member_code="MG-A00001",
        full_name="Allowance Test",
        nik_enc="enc",
        nik_idx="idx",
        balance=balance,
        status="ACTIVE",
    )
    session.add(member)
    session.flush()
    return member


def seed_device(session, number, offline_enabled=True):
    device = Device(
        device_id=f"VND-{number:03d}",
        name=f"Vending {number}",
        type="vending",
        token_hash=f"{number:064x}",
        status="ACTIVE",
        config_json=json.dumps({"offline_enabled": offline_enabled}),
    )
    session.add(device)
    session.flush()
    return device


def test_allowance_zero_devices_returns_empty_mapping(allowance_session):
    session = allowance_session
    with session.begin():
        member = seed_member(session)
        member_id = member.id
    assert AllowanceService(session).compute_allowances_for_member(member_id) == {}


def test_allowance_two_devices_split_balance_by_cap(allowance_session):
    session = allowance_session
    with session.begin():
        member = seed_member(session, 30_000)
        first = seed_device(session, 1)
        second = seed_device(session, 2)
        session.add(Setting(key="offline_card_cap", value="50000"))
        session.flush()
        member_id = member.id
        device_ids = {first.id, second.id}
    computed = AllowanceService(session).compute_allowances_for_member(member_id)
    assert computed == {device_id: 15_000 for device_id in device_ids}


def test_allowance_persists_to_offline_allowances(allowance_session):
    session = allowance_session
    with session.begin():
        member = seed_member(session, 30_000)
        first = seed_device(session, 1)
        second = seed_device(session, 2)
        member_id = member.id
        device_ids = {first.id, second.id}
    service = AllowanceService(session)
    service.apply_allowances(member_id)
    session.commit()
    rows = session.scalars(
        select(OfflineAllowance).where(OfflineAllowance.member_id == member_id)
    ).all()
    assert {row.device_id for row in rows} == device_ids
    assert {row.amount for row in rows} == {15_000}
