"""Public model package; importing it registers every table in Base.metadata."""

from app.models.admin import AdminSession, AdminUser
from app.models.audit import AuditLog
from app.models.base import Base, TimestampMixin, utc_now
from app.models.bind import CardBindSession
from app.models.device import Device, DeviceEvent
from app.models.login_attempt import LoginAttempt
from app.models.member import Card, Member
from app.models.operator import Operator, OperatorDevice
from app.models.product import CatalogMeta, Product, VendingSlot
from app.models.settings import Setting
from app.models.txn import (
    OfflineAllowance,
    PendingSyncLog,
    ShortfallRecord,
    TopUpRequest,
    Transaction,
)

__all__ = [
    "AdminSession",
    "AdminUser",
    "AuditLog",
    "Base",
    "Card",
    "CardBindSession",
    "CatalogMeta",
    "Device",
    "DeviceEvent",
    "LoginAttempt",
    "Member",
    "OfflineAllowance",
    "Operator",
    "OperatorDevice",
    "PendingSyncLog",
    "Product",
    "Setting",
    "ShortfallRecord",
    "TimestampMixin",
    "TopUpRequest",
    "Transaction",
    "VendingSlot",
    "utc_now",
]
