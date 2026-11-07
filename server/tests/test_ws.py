"""Real TestClient WebSocket handshake, authentication, and heartbeat tests."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.websockets import WebSocketDisconnect

from app import db
from app.main import app
from app.models import Base, Device, DeviceEvent
from app.security.device_token import generate_device_token, hash_device_token


def _database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'ws.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", factory)
    return engine, factory


def _device(factory, token, status="ACTIVE"):
    with factory.begin() as session:
        session.add(Device(device_id="CSH-WS", name="WS test", type="cashier",
                           token_hash=hash_device_token(token), status=status,
                           reported_mode="manual", slot_count=0))


def _hello(token, device_id="CSH-WS"):
    return {"v": 1, "id": "hello-1", "type": "hello", "ts": 1,
            "data": {"device_id": device_id, "token": token, "fw_version": "test-1"}}


def test_hello_success_and_ws_connected_flag(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/device") as ws:
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
            assert session.scalars(select(DeviceEvent)).all()
    finally:
        engine.dispose()


def test_hello_missing_and_invalid_token_close_codes(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/device") as ws:
                ws.send_json({"v": 1, "id": "x", "type": "ping", "ts": 1, "data": {}})
                try:
                    ws.receive_text()
                    assert False, "expected close"
                except WebSocketDisconnect as exc:
                    assert exc.code == 4002
            with client.websocket_connect("/ws/device") as ws:
                ws.send_json(_hello("wrong-token"))
                try:
                    ws.receive_text()
                    assert False, "expected close"
                except WebSocketDisconnect as exc:
                    assert exc.code == 4003
    finally:
        engine.dispose()


def test_ping_pong_echoes_message_id(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path, monkeypatch)
    token = generate_device_token()
    _device(factory, token)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/device") as ws:
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
        with TestClient(app) as client:
            with client.websocket_connect("/ws/device") as ws:
                ws.send_json(_hello(token))
                try:
                    ws.receive_text()
                    assert False, "expected close"
                except WebSocketDisconnect as exc:
                    assert exc.code == 4003
    finally:
        engine.dispose()
