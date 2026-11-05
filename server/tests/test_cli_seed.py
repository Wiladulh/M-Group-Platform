"""Idempotent minimal seed command tests."""

from io import StringIO

from app.cli import seed_minimal
from app.models import AdminUser, Base, Device
from app.security.device_token import verify_device_token
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker


def make_factory(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_seed_minimal_creates_admin_and_devices(tmp_path):
    engine, factory = make_factory(tmp_path / "seed.db")
    output = StringIO()
    try:
        assert seed_minimal(
            factory,
            {"ADMIN_USERNAME": "owner", "ADMIN_PASSWORD": "StrongPass123"},
            output,
        ) == 0
        with factory() as session:
            admin = session.scalar(select(AdminUser))
            assert admin.username == "owner"
            assert admin.must_change_password is True
            devices = session.scalars(select(Device).order_by(Device.device_id)).all()
            assert [row.device_id for row in devices] == ["CSH-001", "VND-001", "VND-002"]
            assert [row.slot_count for row in devices] == [0, 5, 5]
            assert all(row.status == "ACTIVE" for row in devices)
            assert all(row.token_hash != "" and len(row.token_hash) == 64 for row in devices)
        lines = output.getvalue().splitlines()
        keys = {
            line.split(" Device Key: ", 1)[0]: line.split(" Device Key: ", 1)[1]
            for line in lines
            if " Device Key: " in line
        }
        assert set(keys) == {"CSH-001", "VND-001", "VND-002"}
        with factory() as session:
            for device_id, token in keys.items():
                row = session.scalar(select(Device).where(Device.device_id == device_id))
                assert verify_device_token(token, row.token_hash)
                assert token not in row.token_hash
    finally:
        engine.dispose()


def test_seed_minimal_is_idempotent_and_does_not_rotate_credentials(tmp_path):
    engine, factory = make_factory(tmp_path / "seed-twice.db")
    try:
        first = StringIO()
        env = {"ADMIN_USERNAME": "owner", "ADMIN_PASSWORD": "StrongPass123"}
        assert seed_minimal(factory, env, first) == 0
        with factory() as session:
            original_hash = session.scalar(select(AdminUser.password_hash))
            original_keys = {
                row.device_id: row.token_hash for row in session.scalars(select(Device)).all()
            }
        second = StringIO()
        assert seed_minimal(
            factory, {"ADMIN_USERNAME": "changed", "ADMIN_PASSWORD": "OtherPass123"}, second
        ) == 0
        with factory() as session:
            assert len(session.scalars(select(AdminUser)).all()) == 1
            assert len(session.scalars(select(Device)).all()) == 3
            assert session.scalar(select(AdminUser.password_hash)) == original_hash
            assert {
                row.device_id: row.token_hash for row in session.scalars(select(Device)).all()
            } == original_keys
        assert "Device Key:" not in second.getvalue()
    finally:
        engine.dispose()


def test_seed_minimal_requires_environment(tmp_path):
    engine, factory = make_factory(tmp_path / "missing-env.db")
    try:
        assert seed_minimal(factory, {}, StringIO()) == 2
        with factory() as session:
            assert session.scalar(select(AdminUser)) is None
            assert session.scalars(select(Device)).all() == []
    finally:
        engine.dispose()
