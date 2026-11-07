"""Remote card binding service and real WebSocket state-machine tests."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from app import db
from app.errors import DomainError
from app.main import app
from app.models import (
    AdminUser,
    Base,
    Card,
    CardBindSession,
    Device,
    Member,
    OfflineAllowance,
)
from app.security.device_token import generate_device_token, hash_device_token
from app.security.passwords import hash_password
from app.services.bind_expiry import bind_expiry_once
from app.services.binding import BindingService
from app.services.events import (
    CacheInvalidateEvent,
    CacheUpdateEvent,
    CardStatusChangedEvent,
    _bus,
)
from app.ws.commands import send_bind_done, send_bind_start
from app.ws.connection_manager import manager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


def _database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'binding.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", factory)
    token = generate_device_token()
    with factory.begin() as session:  # noqa: SIM117
        session.add(
            AdminUser(
                id=1,
                username="admin",
                display_name="Administrator",
                password_hash=hash_password("ci-password-123"),
                must_change_password=False,
            )
        )
        member = Member(
            member_code="MG-A00001",
            full_name="Member Test",
            nik_enc="enc",
            nik_idx="idx-1",
            balance=10_000,
            status="ACTIVE",
        )
        device = Device(
            device_id="CSH-BIND",
            name="Binding cashier",
            type="cashier",
            token_hash=hash_device_token(token),
            status="ACTIVE",
            reported_mode="manual",
            slot_count=5,
        )
        session.add_all([member, device])
        session.flush()
        member_id, device_id = member.id, device.id
    return engine, factory, member_id, device_id, token


def _create_session(factory, member_id, device_id, mode="NEW_CARD"):
    with factory.begin() as session:  # noqa: SIM117
        row = BindingService(session).create_session(member_id, device_id, mode, 1)
        return row.session_uuid


def _scan(factory, session_uuid, uid):
    with factory.begin() as session:  # noqa: SIM117
        return BindingService(session).on_card_scanned(session_uuid, uid, datetime.now(UTC))


def _pin(factory, session_uuid, pin="4610", confirm="4610"):
    with factory.begin() as session:  # noqa: SIM117
        return BindingService(session).on_pin_submitted(session_uuid, pin, confirm)


def _add_member(factory, member_code="MG-A00002", nik_idx="idx-2"):
    with factory.begin() as session:  # noqa: SIM117
        member = Member(
            member_code=member_code,
            full_name="Member Two",
            nik_enc="enc",
            nik_idx=nik_idx,
            balance=0,
            status="ACTIVE",
        )
        session.add(member)
        session.flush()
        return member.id


def _add_device(factory, device_id="CSH-BIND-2"):
    with factory.begin() as session:  # noqa: SIM117
        device = Device(
            device_id=device_id,
            name="Second cashier",
            type="cashier",
            token_hash=hash_device_token(generate_device_token()),
            status="ACTIVE",
            reported_mode="manual",
            slot_count=5,
        )
        session.add(device)
        session.flush()
        return device.id


def _add_card(factory, member_id, uid="AABBCCDD", status="ACTIVE", pin_fail_count=0):
    with factory.begin() as session:  # noqa: SIM117
        card = Card(
            member_id=member_id,
            uid=uid,
            pin_hash="old-pin-hash",
            status=status,
            pin_fail_count=pin_fail_count,
            bound_at=datetime.now(UTC) - timedelta(days=1),
        )
        session.add(card)
        session.flush()
        return card.id


def test_create_session_new_card(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    try:
        session_uuid = _create_session(factory, member_id, device_id)
        with factory() as session:
            row = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            assert row.state == "WAITING_DEVICE"
            assert row.mode == "NEW_CARD"
            assert row.expires_at > datetime.now(UTC)
    finally:
        engine.dispose()


def test_create_session_one_per_device_conflict(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    second_member_id = _add_member(factory)
    try:
        _create_session(factory, member_id, device_id)
        with factory.begin() as session:  # noqa: SIM117
            with pytest.raises(DomainError) as exc:
                BindingService(session).create_session(second_member_id, device_id, "NEW_CARD", 1)
        assert exc.value.code == "BIND_CONFLICT"
    finally:
        engine.dispose()


def test_create_session_one_per_member_conflict(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    second_device_id = _add_device(factory)
    try:
        _create_session(factory, member_id, device_id)
        with factory.begin() as session:  # noqa: SIM117
            with pytest.raises(DomainError) as exc:
                BindingService(session).create_session(member_id, second_device_id, "NEW_CARD", 1)
        assert exc.value.code == "BIND_CONFLICT"
    finally:
        engine.dispose()


def test_new_card_happy_path_end_to_end_over_real_websocket(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, token = _database(tmp_path, monkeypatch)
    session_uuid = _create_session(factory, member_id, device_id)
    published = []
    unsubscribe_cache = _bus.subscribe(CacheUpdateEvent, published.append)
    unsubscribe_status = _bus.subscribe(CardStatusChangedEvent, published.append)
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/device") as ws:
            ws.send_json({
                "v": 1, "id": "hello-bind", "type": "hello", "ts": 1,
                "data": {"device_id": "CSH-BIND", "token": token, "fw_version": "test"},
            })
            assert ws.receive_json()["type"] == "hello_ok"
            ws.send_json({
                "v": 1, "id": "scan-1", "type": "bind.card_scanned", "ts": 2,
                "data": {"session_uuid": session_uuid, "uid": "AABBCCDD", "ts": 2},
            })
            ws.send_json({
                "v": 1, "id": "pin-1", "type": "bind.pin_submitted", "ts": 3,
                "data": {"session_uuid": session_uuid, "pin": "4610", "confirm": "4610", "ts": 3},
            })
            messages = []
            for _ in range(4):
                message = ws.receive_json()
                messages.append(message)
                if message["type"] == "bind.done":
                    assert message["data"]["uid_masked"] == "••••CCDD"
                    ws.send_json({
                        "v": 1, "id": "ack-done", "type": "ack", "ts": 4,
                        "data": {"id": message["id"]},
                    })
                    break
            assert any(message["type"] == "bind.done" for message in messages)
        with factory() as session:
            bind = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            card = session.scalar(select(Card).where(Card.uid == "AABBCCDD"))
            assert bind.state == "DONE"
            assert card.status == "ACTIVE"
            assert card.pin_fail_count == 0
            assert session.get(Member, member_id).balance == 10_000
        assert any(isinstance(event, CacheUpdateEvent) for event in published)
        assert any(isinstance(event, CardStatusChangedEvent) for event in published)
    finally:
        unsubscribe_cache()
        unsubscribe_status()
        engine.dispose()


def test_new_card_uid_conflict_marks_session_failed(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    other_member_id = _add_member(factory)
    _add_card(factory, other_member_id)
    session_uuid = _create_session(factory, member_id, device_id)
    try:
        with factory.begin() as session:  # noqa: SIM117
            with pytest.raises(DomainError) as exc:
                BindingService(session).on_card_scanned(
                    session_uuid, "AABBCCDD", datetime.now(UTC)
                )
        assert exc.value.code == "BIND_CONFLICT"
        with factory() as session:
            row = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            assert row.state == "FAILED"
    finally:
        engine.dispose()


def test_new_card_weak_pin_keeps_confirm_state_for_retry(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    session_uuid = _create_session(factory, member_id, device_id)
    _scan(factory, session_uuid, "AABBCCDD")
    try:
        with factory.begin() as session:  # noqa: SIM117
            with pytest.raises(DomainError) as exc:
                BindingService(session).on_pin_submitted(session_uuid, "1234", "1234")
        assert exc.value.code == "VALIDATION_ERROR"
        assert "PIN terlalu mudah" in str(exc.value)
        with factory() as session:
            row = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            assert row.state == "CONFIRM_PIN"
    finally:
        engine.dispose()


def test_pin_mismatch_three_times_fails_session(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    session_uuid = _create_session(factory, member_id, device_id)
    _scan(factory, session_uuid, "AABBCCDD")
    try:
        for attempt in range(3):
            with factory.begin() as session:  # noqa: SIM117
                with pytest.raises(DomainError) as exc:
                    BindingService(session).on_pin_submitted(session_uuid, "4610", "9999")
            if attempt == 2:
                assert exc.value.code == "BIND_FAILED"
        with factory() as session:
            row = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            assert row.state == "FAILED"
            assert row.pin_attempts == 3
            assert row.failure_reason == "PIN tidak cocok 3 kali"
    finally:
        engine.dispose()


def test_replace_card_happy_path_is_atomic_and_deletes_allowance(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    old_card_id = _add_card(factory)
    with factory.begin() as session:  # noqa: SIM117
        session.add(
            OfflineAllowance(
                member_id=member_id,
                device_id=device_id,
                amount=1_000,
                computed_at=datetime.now(UTC),
                version=1,
            )
        )
    session_uuid = _create_session(factory, member_id, device_id, "REPLACE_CARD")
    invalidations = []
    unsubscribe = _bus.subscribe(CacheInvalidateEvent, invalidations.append)
    try:
        _scan(factory, session_uuid, "11223344")
        _pin(factory, session_uuid)
        with factory() as session:
            old_card = session.get(Card, old_card_id)
            new_card = session.scalar(select(Card).where(Card.uid == "11223344"))
            assert old_card.status == "REPLACED"
            assert old_card.deactivated_reason == "card_replaced"
            assert new_card.status == "ACTIVE"
            assert session.get(Member, member_id).balance == 10_000
            assert session.scalars(
                select(OfflineAllowance).where(OfflineAllowance.member_id == member_id)
            ).all() == []
        assert invalidations and invalidations[0].uid_list == ["AABBCCDD"]
    finally:
        unsubscribe()
        engine.dispose()


def test_pin_only_unlocks_card_and_resets_pin_fail_count(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    card_id = _add_card(factory, status="LOCKED", pin_fail_count=3)
    session_uuid = _create_session(factory, member_id, device_id, "PIN_ONLY")
    try:
        _scan(factory, session_uuid, "AABBCCDD")
        _pin(factory, session_uuid)
        with factory() as session:
            card = session.get(Card, card_id)
            assert card.status == "ACTIVE"
            assert card.pin_fail_count == 0
            assert card.bound_at > datetime.now(UTC) - timedelta(minutes=1)
    finally:
        engine.dispose()


def test_pin_only_wrong_member_uid_returns_bind_conflict(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    other_member_id = _add_member(factory)
    _add_card(factory, other_member_id)
    session_uuid = _create_session(factory, member_id, device_id, "PIN_ONLY")
    try:
        with factory.begin() as session:  # noqa: SIM117
            with pytest.raises(DomainError) as exc:
                BindingService(session).on_card_scanned(
                    session_uuid, "AABBCCDD", datetime.now(UTC)
                )
        assert exc.value.code == "BIND_CONFLICT"
    finally:
        engine.dispose()


def test_pin_only_unknown_uid_returns_card_unknown(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    session_uuid = _create_session(factory, member_id, device_id, "PIN_ONLY")
    try:
        with factory.begin() as session:  # noqa: SIM117
            with pytest.raises(DomainError) as exc:
                BindingService(session).on_card_scanned(
                    session_uuid, "AABBCCDD", datetime.now(UTC)
                )
        assert exc.value.code == "CARD_UNKNOWN"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_session_expiry_sends_bind_cancel(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    session_uuid = _create_session(factory, member_id, device_id)
    with factory.begin() as session:  # noqa: SIM117
        row = session.scalar(
            select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
        )
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    class FakeSocket:
        sent = []

        async def send_text(self, value):
            self.sent.append(json.loads(value))

    socket = FakeSocket()
    monkeypatch.setitem(manager._connections, device_id, socket)
    try:
        assert await bind_expiry_once(None) == 1
        with factory() as session:
            row = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            assert row.state == "EXPIRED"
        assert socket.sent[0]["type"] == "bind.cancel"
        manager.record_ack(device_id, socket.sent[0]["id"])
    finally:
        engine.dispose()


def test_device_cancel_transitions_session_to_cancelled(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)
    session_uuid = _create_session(factory, member_id, device_id)
    try:
        with factory.begin() as session:  # noqa: SIM117
            row = BindingService(session).on_device_cancel(session_uuid)
            assert row.state == "CANCELLED"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_ack_timeout_is_logged(tmp_path, monkeypatch, caplog):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)

    class FakeSocket:
        async def send_text(self, _value):
            return None

    monkeypatch.setitem(manager._connections, device_id, FakeSocket())
    monkeypatch.setenv("BIND_ACK_TIMEOUT_S", "0.01")
    try:
        assert await send_bind_start(device_id, "session-id", "Member Test", "NEW_CARD", 90)
        await asyncio.sleep(0.03)
        assert "device_ws_ack_timeout" in caplog.text
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_bind_done_masks_uid(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, _token = _database(tmp_path, monkeypatch)

    class FakeSocket:
        sent = None

        async def send_text(self, value):
            self.sent = json.loads(value)

    socket = FakeSocket()
    monkeypatch.setitem(manager._connections, device_id, socket)
    try:
        assert await send_bind_done(device_id, "session-id", "AABBCCDDEEFF", "ACTIVE")
        assert socket.sent["data"]["uid_masked"] == "••••DDEEFF"
        manager.record_ack(device_id, socket.sent["id"])
    finally:
        engine.dispose()



def test_device_cancel_over_real_websocket(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, token = _database(tmp_path, monkeypatch)
    session_uuid = _create_session(factory, member_id, device_id)
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/device") as ws:
            ws.send_json({
                "v": 1, "id": "hello-cancel", "type": "hello", "ts": 1,
                "data": {"device_id": "CSH-BIND", "token": token, "fw_version": "test"},
            })
            assert ws.receive_json()["type"] == "hello_ok"
            ws.send_json({
                "v": 1, "id": "cancel-1", "type": "bind.cancel", "ts": 2,
                "data": {"session_uuid": session_uuid, "reason": "operator_cancelled"},
            })
            response = ws.receive_json()
            assert response["type"] == "bind.cancel"
            assert response["data"]["reason"] == "operator_cancelled"
            ws.send_json({
                "v": 1, "id": "ack-cancel", "type": "ack", "ts": 3,
                "data": {"id": response["id"]},
            })
        with factory() as session:
            row = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            assert row.state == "CANCELLED"
    finally:
        engine.dispose()



@pytest.mark.asyncio
async def test_bind_expiry_loop_uses_five_second_interval(monkeypatch):
    from app.services import bind_expiry as expiry_module

    calls = []

    async def stop_after_first_sleep(seconds):
        calls.append(seconds)
        raise asyncio.CancelledError

    async def expire_once(_app):
        return 0

    monkeypatch.setattr(expiry_module.asyncio, "sleep", stop_after_first_sleep)
    monkeypatch.setattr(expiry_module, "bind_expiry_once", expire_once)
    with pytest.raises(asyncio.CancelledError):
        await expiry_module.bind_expiry_loop(None)
    assert calls == [5]
