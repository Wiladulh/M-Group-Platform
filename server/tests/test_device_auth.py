"""Device bearer authentication, config merge, and settings service tests."""

from app import db
from app.main import app
from app.models import Base, Device, Setting
from app.security.device_auth import DeviceAuthInfo, _update_presence, require_device
from app.security.device_token import generate_device_token, hash_device_token
from app.services.settings import get_all_settings, get_setting, set_setting
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker


def make_test_db(path, monkeypatch):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", factory)
    return engine, factory


def add_device(factory, token, *, status="ACTIVE", config_json=None):
    with factory.begin() as session:
        session.add(
            Device(
                device_id="CSH-001",
                name="Cashier Test",
                type="cashier",
                reported_mode="manual",
                slot_count=0,
                token_hash=hash_device_token(token),
                status=status,
                config_json=config_json,
            )
        )


def _register_test_route(path, endpoint):
    router = APIRouter()
    router.add_api_route(path, endpoint, methods=["GET"])
    app.include_router(router)
    return path


def _remove_test_route(path):
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "path", None) != path
    ]


def test_valid_device_token_returns_config_and_updates_last_seen(tmp_path, monkeypatch):
    engine, factory = make_test_db(tmp_path / "auth.db", monkeypatch)
    token = generate_device_token()
    add_device(factory, token)
    try:
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}", "X-Device-Id": "CSH-001"}
            first = client.get("/api/v1/device/config", headers=headers)
            assert first.status_code == 200
            payload = first.json()
            assert payload["device_id"] == "CSH-001"
            assert isinstance(payload["offline_enabled"], bool)
            assert payload["server_time_utc"].endswith("Z")
            with factory() as session:
                first_seen = session.scalar(select(Device.last_seen_at))
            second = client.get("/api/v1/device/config", headers=headers)
            assert second.status_code == 200
            with factory() as session:
                second_seen = session.scalar(select(Device.last_seen_at))
            assert first_seen is not None and second_seen is not None
            assert second_seen >= first_seen
    finally:
        engine.dispose()


def test_require_device_returns_auth_info(tmp_path, monkeypatch):
    engine, factory = make_test_db(tmp_path / "auth-info.db", monkeypatch)
    token = generate_device_token()
    add_device(factory, token, config_json='{"mode":"scanner"}')

    def auth_info_endpoint(  # noqa: B008
        device: DeviceAuthInfo = Depends(require_device),
    ):
        return {
            "class": type(device).__name__,
            "id": device.id,
            "device_id": device.device_id,
            "name": device.name,
            "type": device.type,
            "config_json": device.config_json,
            "slot_count": device.slot_count,
            "reported_mode": device.reported_mode,
        }

    path = "/__test/device-auth-info"
    _register_test_route(path, auth_info_endpoint)
    try:
        with TestClient(app) as client:
            response = client.get(
                path,
                headers={"Authorization": f"Bearer {token}", "X-Device-Id": "CSH-001"},
            )
        assert response.status_code == 200
        assert response.json() == {
            "class": "DeviceAuthInfo",
            "id": 1,
            "device_id": "CSH-001",
            "name": "Cashier Test",
            "type": "cashier",
            "config_json": '{"mode":"scanner"}',
            "slot_count": 0,
            "reported_mode": "manual",
        }
    finally:
        _remove_test_route(path)
        engine.dispose()


def test_auth_session_does_not_leak_into_handler(tmp_path, monkeypatch):
    engine, factory = make_test_db(tmp_path / "clean-handler-session.db", monkeypatch)
    token = generate_device_token()
    add_device(factory, token)

    def transaction_endpoint(
        _device: DeviceAuthInfo = Depends(require_device),  # noqa: B008
        session: Session = Depends(db.get_session),  # noqa: B008
    ):
        with session.begin():
            result = session.execute(text("SELECT 1")).scalar_one()
        return {"result": result}

    path = "/__test/clean-handler-session"
    _register_test_route(path, transaction_endpoint)
    try:
        with TestClient(app) as client:
            response = client.get(
                path,
                headers={"Authorization": f"Bearer {token}", "X-Device-Id": "CSH-001"},
            )
        assert response.status_code == 200
        assert response.json() == {"result": 1}
    finally:
        _remove_test_route(path)
        engine.dispose()


def test_auth_session_closed_after_request(tmp_path, monkeypatch):
    engine, factory = make_test_db(tmp_path / "auth-session-close.db", monkeypatch)
    token = generate_device_token()
    add_device(factory, token)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/device/config",
                headers={"Authorization": f"Bearer {token}", "X-Device-Id": "CSH-001"},
            )
        assert response.status_code == 200
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_missing_authorization_returns_device_revoked(tmp_path, monkeypatch):
    engine, factory = make_test_db(tmp_path / "missing-auth.db", monkeypatch)
    token = generate_device_token()
    add_device(factory, token)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/device/config",
                headers={"X-Device-Id": "CSH-001"},
            )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "DEVICE_REVOKED"
    finally:
        engine.dispose()


def test_both_credentials_missing_returns_device_revoked(tmp_path, monkeypatch):
    engine, _factory = make_test_db(tmp_path / "no-credentials.db", monkeypatch)
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/device/config")
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Unauthorized device"
    finally:
        engine.dispose()


def test_wrong_token_and_wrong_device_id_are_rejected(tmp_path, monkeypatch):
    engine, factory = make_test_db(tmp_path / "wrong-auth.db", monkeypatch)
    token = generate_device_token()
    add_device(factory, token)
    try:
        with TestClient(app) as client:
            wrong_token = client.get(
                "/api/v1/device/config",
                headers={
                    "Authorization": "Bearer not-the-device-key",
                    "X-Device-Id": "CSH-001",
                },
            )
            wrong_id = client.get(
                "/api/v1/device/config",
                headers={"Authorization": f"Bearer {token}", "X-Device-Id": "VND-999"},
            )
        assert wrong_token.status_code == 401
        assert wrong_id.status_code == 401
    finally:
        engine.dispose()


def test_revoked_device_is_rejected_without_refreshing_last_seen(tmp_path, monkeypatch):
    engine, factory = make_test_db(tmp_path / "revoked.db", monkeypatch)
    token = generate_device_token()
    add_device(factory, token, status="REVOKED")
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/device/config",
                headers={"Authorization": f"Bearer {token}", "X-Device-Id": "CSH-001"},
            )
        assert response.status_code == 401
        with factory() as session:
            row = session.scalar(select(Device))
            assert row.last_seen_at is None
    finally:
        engine.dispose()


def test_config_overrides_global_settings(tmp_path, monkeypatch):
    engine, factory = make_test_db(tmp_path / "override.db", monkeypatch)
    token = generate_device_token()
    add_device(
        factory,
        token,
        config_json='{"offline_enabled":false,"offline_txn_max":12000,"mode":"scanner"}',
    )
    with factory.begin() as session:
        session.add(Setting(key="offline_txn_max", value="25000"))
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/device/config",
                headers={"Authorization": f"Bearer {token}", "X-Device-Id": "CSH-001"},
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["offline_enabled"] is False
        assert payload["offline_txn_max"] == 12000
        assert payload["mode"] == "scanner"
        assert payload["device_config_overrides"]["offline_txn_max"] == 12000
    finally:
        engine.dispose()


def test_failed_auth_does_not_update_last_seen(tmp_path, monkeypatch):
    engine, factory = make_test_db(tmp_path / "no-heartbeat.db", monkeypatch)
    token = generate_device_token()
    add_device(factory, token)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/device/config",
                headers={"Authorization": "Bearer bad-token", "X-Device-Id": "CSH-001"},
            )
        assert response.status_code == 401
        with factory() as session:
            assert session.scalar(select(Device.last_seen_at)) is None
    finally:
        engine.dispose()


def test_presence_task_uses_own_session(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.executed = False
            self.committed = False
            self.closed = False

        def execute(self, statement):
            self.executed = True

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError("rollback must not be called")

        def close(self):
            self.closed = True

    created = []

    def session_factory():
        session = FakeSession()
        created.append(session)
        return session

    monkeypatch.setattr(db, "SessionLocal", session_factory)
    _update_presence(1, "127.0.0.1")
    assert len(created) == 1
    assert created[0].executed is True
    assert created[0].committed is True
    assert created[0].closed is True


def test_settings_helpers_cast_upsert_and_list(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'settings.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory.begin() as session:
            assert get_setting(session, "missing_int", 12) == 12
            set_setting(session, "offline_enabled", True)
            set_setting(session, "offline_txn_max", 30000)
        with factory.begin() as session:
            assert get_setting(session, "offline_enabled", False) is True
            assert get_setting(session, "offline_txn_max", 0) == 30000
            set_setting(session, "offline_txn_max", 25000)
        with factory() as session:
            assert (
                session.scalar(select(Setting.value).where(Setting.key == "offline_txn_max"))
                == "25000"
            )
            assert get_all_settings(session) == {"offline_enabled": True, "offline_txn_max": 25000}
    finally:
        engine.dispose()
