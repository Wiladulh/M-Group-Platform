"""Tests for the reset-admin-password CLI command (spec 4.1)."""

from io import StringIO

from app.cli import reset_admin_password
from app.models import AdminUser, AuditLog, Base
from app.security.passwords import verify_password
from app.services.admin_auth import create_admin_session
from argon2 import PasswordHasher
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

OLD_PASSWORD = "OldPassword123"
NEW_PASSWORD = "NewPassword456"


def _factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reset.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    admin = AdminUser(
        id=1,
        username="owner1234567",
        display_name="Owner",
        password_hash=PasswordHasher().hash(OLD_PASSWORD),
        must_change_password=False,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    create_admin_session(db, admin, "127.0.0.1", "pytest", 1440)
    create_admin_session(db, admin, "127.0.0.2", "pytest", 1440)
    db.commit()
    db.close()
    return engine, factory


def _answers(*values):
    queue = list(values)
    return lambda _prompt: queue.pop(0)


def test_reset_changes_password_revokes_sessions_and_audits(tmp_path):
    engine, factory = _factory(tmp_path)
    try:
        out = StringIO()
        code = reset_admin_password(factory, _answers(NEW_PASSWORD, NEW_PASSWORD), out)
        assert code == 0
        db = factory()
        admin = db.scalar(select(AdminUser).where(AdminUser.id == 1))
        assert verify_password(NEW_PASSWORD, admin.password_hash)
        assert not verify_password(OLD_PASSWORD, admin.password_hash)
        from app.models import AdminSession

        active = db.scalars(select(AdminSession).where(AdminSession.revoked_at.is_(None))).all()
        assert active == []
        audit = db.scalars(select(AuditLog).where(AuditLog.action == "ADMIN_PASSWORD_RESET")).one()
        assert '"revoked_sessions": 2' in audit.after_json
        assert NEW_PASSWORD not in (audit.after_json or "")
        db.close()
        assert "berhasil" in out.getvalue()
    finally:
        engine.dispose()


def test_reset_rejects_mismatched_confirmation(tmp_path):
    engine, factory = _factory(tmp_path)
    try:
        out = StringIO()
        code = reset_admin_password(factory, _answers(NEW_PASSWORD, "Lain12345678"), out)
        assert code == 1
        db = factory()
        admin = db.scalar(select(AdminUser).where(AdminUser.id == 1))
        assert verify_password(OLD_PASSWORD, admin.password_hash)
        db.close()
        assert "tidak sama" in out.getvalue()
    finally:
        engine.dispose()


def test_reset_rejects_weak_or_reused_password(tmp_path):
    engine, factory = _factory(tmp_path)
    try:
        weak = StringIO()
        assert reset_admin_password(factory, _answers("short1", "short1"), weak) == 1
        assert "minimal 10" in weak.getvalue()

        reused = StringIO()
        assert reset_admin_password(factory, _answers(OLD_PASSWORD, OLD_PASSWORD), reused) == 1
        assert "sebelumnya" in reused.getvalue()

        same_as_user = StringIO()
        assert (
            reset_admin_password(factory, _answers("owner1234567", "owner1234567"), same_as_user)
            == 1
        )
        assert "username" in same_as_user.getvalue()
    finally:
        engine.dispose()


def test_reset_without_admin_row_fails_cleanly(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        out = StringIO()
        assert reset_admin_password(factory, _answers(NEW_PASSWORD, NEW_PASSWORD), out) == 1
        assert "seed-minimal" in out.getvalue()
    finally:
        engine.dispose()
