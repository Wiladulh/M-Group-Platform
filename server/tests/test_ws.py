"""Real TestClient WebSocket handshake, lifecycle, broadcast, and heartbeat tests."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app import db
from app.config import get_settings
from app.main import app
from app.models import Base, Device, DeviceEvent
from app.security.device_token import generate_device_token, hash_device_token
from app.services import offline_monitor
from app.services.events import CacheUpdateEvent, CardStatusChangedEvent, _bus
from app.services.offline_monitor import offline_monitor_once
from app.ws.connection_manager import manager
from app.ws.heartbeat import heartbeat
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect


def _database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ws.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", factory)
    return engine, factory


def _device(factory, token, status="ACTIVE", device_id="CSH-WS"):
    with factory.begin() as session:
        session.add(
            Device(
                device_id=device_id,
                name="WS test",
                type="cashier",
                token_hash=hash_device_token(token),
                status=status,
                reported_mode="manual",
                slot_count=0,
            )
        )


def _hello(token, device_id="CSH-WS", message_id="hello-1"):
    return {
        "v": 1,
        "id": message_id,
        "type": "hello",
        "ts": 1,
        "data": {"device_id": device_id, "token": token, "fw_version": "test-1"},
    }


def test_hello_success_and_ws_connected_flag(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/device") as ws:
            ws.send_json(_hello(token))
            response = ws.receive_json()
            assert response["type"] == "hello_ok"
            assert response["id"] == "hello-1"
            assert response["data"]["ping_interval_s"] == 10
            assert response["data"]["pong_timeout_s"] == 25
            assert response["data"]["idle_disconnect_s"] == 30
            with factory() as session:
                assert session.scalar(select(Device.ws_connected)) is True
        with factory() as session:
            assert session.scalar(select(Device.ws_connected)) is False
            events = session.scalars(select(DeviceEvent)).all()
            assert {event.event for event in events} == {"ONLINE", "OFFLINE"}
    finally:
        engine.dispose()


def test_hello_missing_and_invalid_token_close_codes(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    try:
        with TestClient(app) as client:  # noqa: SIM117
            with client.websocket_connect("/ws/device") as ws:
                ws.send_json({"v": 1, "id": "x", "type": "ping", "ts": 1, "data": {}})
                with pytest.raises(WebSocketDisconnect) as exc:
                    ws.receive_text()
                assert exc.value.code == 4002
            with client.websocket_connect("/ws/device") as ws:
                ws.send_json(_hello("wrong-token"))
                with pytest.raises(WebSocketDisconnect) as exc:
                    ws.receive_text()
                assert exc.value.code == 4003
    finally:
        engine.dispose()


def test_ping_pong_echoes_message_id(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/device") as ws:
            ws.send_json(_hello(token))
            ws.receive_json()
            ws.send_json({"v": 1, "id": "ping-xyz", "type": "ping", "ts": 2, "data": {}})
            pong = ws.receive_json()
            assert pong["type"] == "pong" and pong["id"] == "ping-xyz"
    finally:
        engine.dispose()


def test_revoked_device_rejected(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token, status="REVOKED")
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/device") as ws:
            ws.send_json(_hello(token))
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            assert exc.value.code == 4003
    finally:
        engine.dispose()


def test_one_active_connection_per_device_closes_old_socket_4001(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    try:
        with TestClient(app) as client:  # noqa: SIM117
            with client.websocket_connect("/ws/device") as first:
                first.send_json(_hello(token, message_id="first"))
                assert first.receive_json()["type"] == "hello_ok"
                with client.websocket_connect("/ws/device") as second:
                    second.send_json(_hello(token, message_id="second"))
                    assert second.receive_json()["type"] == "hello_ok"
                    with pytest.raises(WebSocketDisconnect) as exc:
                        first.receive_text()
                    assert exc.value.code == 4001
                    assert manager.connected_count() == 1
    finally:
        engine.dispose()


def test_unexpected_bind_start_from_device_is_ignored(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/device") as ws:
            ws.send_json(_hello(token))
            ws.receive_json()
            ws.send_json(
                {
                    "v": 1,
                    "id": "bind-1",
                    "type": "bind.start",
                    "ts": 2,
                    "data": {"session_uuid": "session"},
                }
            )
            ws.send_json({"v": 1, "id": "ping-after-bind", "type": "ping", "ts": 3, "data": {}})
            assert ws.receive_json()["id"] == "ping-after-bind"
    finally:
        engine.dispose()


def test_idle_timeout_closes_4005(tmp_path, monkeypatch):
    from app.ws import handlers

    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    monkeypatch.setattr(handlers, "IDLE_DISCONNECT_S", 0.01)
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/device") as ws:
            ws.send_json(_hello(token))
            ws.receive_json()
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            assert exc.value.code == 4005
    finally:
        engine.dispose()


def test_cache_update_broadcast_to_all_connected_devices(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token_a, token_b = generate_device_token(), generate_device_token()
    _device(factory, token_a, device_id="CSH-A")
    _device(factory, token_b, device_id="CSH-B")
    try:
        with TestClient(app) as client:  # noqa: SIM117
            with client.websocket_connect("/ws/device") as ws_a:
                ws_a.send_json(_hello(token_a, "CSH-A", "hello-a"))
                ws_a.receive_json()
                with client.websocket_connect("/ws/device") as ws_b:
                    ws_b.send_json(_hello(token_b, "CSH-B", "hello-b"))
                    ws_b.receive_json()
                    _bus.publish(
                        CacheUpdateEvent(
                            member_id=1,
                            uid_list=["AABBCCDD"],
                            balance_snapshot=9000,
                            offline_allowance={1: 2000, 2: 3000},
                            card_status="ACTIVE",
                            computed_at_utc=datetime.now(UTC).isoformat(),
                        )
                    )
                    update_a = ws_a.receive_json()
                    update_b = ws_b.receive_json()
                    assert update_a["type"] == update_b["type"] == "cache.update"
                    assert update_a["data"]["uid"] == update_b["data"]["uid"] == "AABBCCDD"
                    assert update_a["data"]["offline_allowance"] == 2000
                    assert update_b["data"]["offline_allowance"] == 3000
    finally:
        engine.dispose()


def test_card_status_changed_broadcast_to_all_connected_devices(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token_a, token_b = generate_device_token(), generate_device_token()
    _device(factory, token_a, device_id="CSH-A")
    _device(factory, token_b, device_id="CSH-B")
    try:
        with TestClient(app) as client:  # noqa: SIM117
            with client.websocket_connect("/ws/device") as ws_a:
                ws_a.send_json(_hello(token_a, "CSH-A", "hello-a"))
                ws_a.receive_json()
                with client.websocket_connect("/ws/device") as ws_b:
                    ws_b.send_json(_hello(token_b, "CSH-B", "hello-b"))
                    ws_b.receive_json()
                    _bus.publish(CardStatusChangedEvent(uid="AABBCCDD", status="LOCKED"))
                    event_a = ws_a.receive_json()
                    event_b = ws_b.receive_json()
                    assert event_a["type"] == event_b["type"] == "card.status_changed"
                    assert (
                        event_a["data"]
                        == event_b["data"]
                        == {"uid": "AABBCCDD", "status": "LOCKED"}
                    )
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_heartbeat_timeout_closes_4006(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    with factory.begin() as session:
        device = Device(
            device_id="CSH-HB",
            name="Heartbeat",
            type="cashier",
            token_hash=hash_device_token(generate_device_token()),
            status="ACTIVE",
        )
        session.add(device)
        session.flush()
        device_pk = device.id

    class FakeSocket:
        code = None

        async def close(self, code, reason):
            self.code = code

    socket = FakeSocket()
    monkeypatch.setitem(manager._connections, device_pk, socket)
    monkeypatch.setitem(manager._connected_since, device_pk, datetime.now(UTC))
    monkeypatch.setattr(heartbeat, "is_alive", lambda _device_pk: False)
    try:
        await offline_monitor_once(None)
        assert socket.code == 4006
        assert await manager.is_connected(device_pk) is False
        with factory() as session:
            assert session.scalar(select(Device.ws_connected)) is False
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_offline_alert_webhook_fired_once(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    old = datetime.now(UTC) - timedelta(minutes=5)
    with factory.begin() as session:
        device = Device(
            device_id="CSH-ALERT",
            name="Alert",
            type="cashier",
            token_hash=hash_device_token(generate_device_token()),
            status="ACTIVE",
            last_seen_at=old,
            ws_connected=False,
        )
        session.add(device)
        session.flush()
        session.add(DeviceEvent(device_id=device.id, event="OFFLINE", at=old, duration_s=None))
    monkeypatch.setattr(get_settings(), "alert_webhook_url", "https://alerts.example/hook")
    calls = []

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, json):
            calls.append((url, json))

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    try:
        await offline_monitor_once(None)
        await asyncio.sleep(0.01)
        assert len(calls) == 1
        assert calls[0][0] == "https://alerts.example/hook"
        assert calls[0][1]["event"] == "offline"
        assert calls[0][1]["device"] == "CSH-ALERT"
    finally:
        engine.dispose()


def test_no_pin_or_token_in_logs(tmp_path, monkeypatch, caplog):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    try:
        with TestClient(app) as client, client.websocket_connect("/ws/device") as ws:
            ws.send_json(_hello(token))
            ws.receive_json()
        assert token not in caplog.text
        assert "CSH-WS" in caplog.text or caplog.text == ""
    finally:
        engine.dispose()


def test_offline_alert_claim_is_idempotent(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    old = datetime.now(UTC) - timedelta(minutes=5)
    with factory.begin() as session:
        device = Device(
            device_id="CSH-ALERT-CLAIM",
            name="Alert claim",
            type="cashier",
            token_hash=hash_device_token(generate_device_token()),
            status="ACTIVE",
            last_seen_at=old,
            ws_connected=False,
        )
        session.add(device)
        session.flush()
        event = DeviceEvent(device_id=device.id, event="OFFLINE", at=old, duration_s=None)
        session.add(event)
        session.flush()
        event_id = event.id

    try:
        with factory() as first_session:
            assert offline_monitor._claim_offline_alert(first_session, event_id) is True
        with factory() as second_session:
            assert offline_monitor._claim_offline_alert(second_session, event_id) is False
        with factory() as session:
            claimed = session.get(DeviceEvent, event_id)
            assert claimed is not None
            assert claimed.detail == "alert_fired"
    finally:
        engine.dispose()
