"""Real WebSocket E2E coverage for REPLACE_CARD and PIN_ONLY binding modes."""

import asyncio
import threading
from datetime import UTC, datetime

import pytest
from app.models import Card, CardBindSession, Member, OfflineAllowance
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from tests.test_binding import _add_card, _add_member, _create_session, _database


def _hello(token: str, device_id: str = "CSH-001") -> dict:
    return {
        "v": 1,
        "id": "hello-binding-e2e",
        "type": "hello",
        "ts": 1,
        "data": {"device_id": device_id, "token": token, "fw_version": "test"},
    }


async def _receive_json(ws) -> dict:
    """Bound every blocking TestClient receive to three seconds."""
    return await asyncio.wait_for(asyncio.to_thread(ws.receive_json), timeout=3)


def _ack(ws, message: dict, sequence: int) -> None:
    ws.send_json(
        {
            "v": 1,
            "id": f"ack-binding-{sequence}",
            "type": "ack",
            "ts": sequence,
            "data": {"id": message["id"]},
        }
    )


async def _connect_and_start(client, token: str, session_uuid: str, mode: str):
    ws = client.websocket_connect("/ws/device")
    ws.__enter__()
    ws.send_json(_hello(token))
    hello_ok = await _receive_json(ws)
    assert hello_ok["type"] == "hello_ok"
    start = await _receive_json(ws)
    assert start["type"] == "bind.start"
    assert start["data"]["mode"] == mode
    assert start["data"]["session_uuid"] == session_uuid
    _ack(ws, start, 2)
    return ws


def _send_scan(ws, session_uuid: str, uid: str) -> None:
    ws.send_json(
        {
            "v": 1,
            "id": "scan-binding-e2e",
            "type": "bind.card_scanned",
            "ts": 3,
            "data": {"session_uuid": session_uuid, "uid": uid, "ts": 3},
        }
    )


def _send_pin(ws, session_uuid: str, pin: str) -> None:
    ws.send_json(
        {
            "v": 1,
            "id": "pin-binding-e2e",
            "type": "bind.pin_submitted",
            "ts": 4,
            "data": {"session_uuid": session_uuid, "pin": pin, "confirm": pin, "ts": 4},
        }
    )


@pytest.mark.asyncio
async def test_replace_card_via_websocket_e2e(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, token = _database(
        tmp_path, monkeypatch, device_code="CSH-001"
    )
    old_card_id = _add_card(factory, member_id, uid="AABBCCDD")
    with factory.begin() as session:
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
    try:
        with TestClient(app) as client:
            ws = await _connect_and_start(client, token, session_uuid, "REPLACE_CARD")
            with ws:
                _send_scan(ws, session_uuid, "11223344")
                with factory() as session:
                    bind = session.scalar(
                        select(CardBindSession).where(
                            CardBindSession.session_uuid == session_uuid
                        )
                    )
                    assert bind.state == "WAITING_PIN"

                _send_pin(ws, session_uuid, "4610")
                received = set()
                for sequence in range(5, 12):
                    message = await _receive_json(ws)
                    message_type = message["type"]
                    if message_type == "bind.done":
                        assert message["data"]["uid_masked"] == "••••3344"
                        assert message["data"]["status"] == "ACTIVE"
                        _ack(ws, message, sequence)
                    if message_type == "card.status_changed":
                        assert message["data"]["uid"] == "11223344"
                        assert message["data"]["status"] == "ACTIVE"
                    received.add(message_type)
                    if {"bind.done", "card.status_changed"} <= received:
                        break
                assert {"bind.done", "card.status_changed"} <= received

        with factory() as session:
            old_card = session.get(Card, old_card_id)
            new_card = session.scalar(select(Card).where(Card.uid == "11223344"))
            bind = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            assert old_card.status == "REPLACED"
            assert new_card.status == "ACTIVE"
            assert new_card.member_id == member_id
            assert session.get(Member, member_id).balance == 10_000
            assert session.scalars(
                select(OfflineAllowance).where(
                    OfflineAllowance.member_id == member_id,
                    OfflineAllowance.device_id == device_id,
                )
            ).all() == []
            assert bind.state == "DONE"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_pin_only_via_websocket_e2e(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, token = _database(
        tmp_path, monkeypatch, device_code="CSH-001"
    )
    card_id = _add_card(factory, member_id, uid="AABBCCDD", status="LOCKED", pin_fail_count=3)
    old_verifier = "old-offline-verifier"
    with factory.begin() as session:
        session.get(Card, card_id).offline_verifier = old_verifier
    session_uuid = _create_session(factory, member_id, device_id, "PIN_ONLY")
    try:
        with TestClient(app) as client:
            ws = await _connect_and_start(client, token, session_uuid, "PIN_ONLY")
            with ws:
                _send_scan(ws, session_uuid, "AABBCCDD")
                _send_pin(ws, session_uuid, "8472")
                done = None
                for sequence in range(5, 9):
                    message = await _receive_json(ws)
                    if message["type"] == "bind.done":
                        done = message
                        assert done["data"]["uid_masked"] == "••••CCDD"
                        assert done["data"]["status"] == "ACTIVE"
                        _ack(ws, done, sequence)
                        break
                assert done is not None

        with factory() as session:
            card = session.get(Card, card_id)
            bind = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            assert card.status == "ACTIVE"
            assert card.pin_fail_count == 0
            assert card.bound_at.replace(tzinfo=UTC) >= bind.created_at.replace(tzinfo=UTC)
            assert card.offline_verifier != old_verifier
            assert card.offline_verifier is not None
            assert bind.state == "DONE"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_replace_card_via_websocket_uid_conflict(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, token = _database(
        tmp_path, monkeypatch, device_code="CSH-001"
    )
    _add_card(factory, member_id, uid="AABBCCDD")
    other_member_id = _add_member(factory)
    _add_card(factory, other_member_id, uid="11223344")
    session_uuid = _create_session(factory, member_id, device_id, "REPLACE_CARD")
    try:
        with TestClient(app) as client:
            ws = await _connect_and_start(client, token, session_uuid, "REPLACE_CARD")
            with ws:
                _send_scan(ws, session_uuid, "11223344")
                error = await _receive_json(ws)
                assert error["type"] == "bind.error"
                assert error["data"]["code"] == "BIND_CONFLICT"
                assert error["data"]["message"] == "Kartu sudah terdaftar pada member lain"
                _ack(ws, error, 5)
        with factory() as session:
            bind = session.scalar(
                select(CardBindSession).where(CardBindSession.session_uuid == session_uuid)
            )
            assert bind.state == "FAILED"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_pin_only_via_websocket_unknown_uid(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, token = _database(
        tmp_path, monkeypatch, device_code="CSH-001"
    )
    session_uuid = _create_session(factory, member_id, device_id, "PIN_ONLY")
    try:
        with TestClient(app) as client:
            ws = await _connect_and_start(client, token, session_uuid, "PIN_ONLY")
            with ws:
                _send_scan(ws, session_uuid, "11223344")
                error = await _receive_json(ws)
                assert error["type"] == "bind.error"
                assert error["data"]["code"] == "CARD_UNKNOWN"
                _ack(ws, error, 5)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_pin_only_via_websocket_wrong_member(tmp_path, monkeypatch):
    engine, factory, member_id, device_id, token = _database(
        tmp_path, monkeypatch, device_code="CSH-001"
    )
    other_member_id = _add_member(factory)
    _add_card(factory, other_member_id, uid="AABBCCDD")
    session_uuid = _create_session(factory, member_id, device_id, "PIN_ONLY")
    try:
        with TestClient(app) as client:
            ws = await _connect_and_start(client, token, session_uuid, "PIN_ONLY")
            with ws:
                _send_scan(ws, session_uuid, "AABBCCDD")
                error = await _receive_json(ws)
                assert error["type"] == "bind.error"
                assert error["data"]["code"] == "BIND_CONFLICT"
                assert error["data"]["message"] == "Kartu sudah terdaftar pada member lain"
                _ack(ws, error, 5)
    finally:
        engine.dispose()
