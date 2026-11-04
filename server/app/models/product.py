"""Product catalog, vending slots, and catalog version metadata."""

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_products_sku"),
        CheckConstraint("price >= 0", name="ck_products_price"),
        CheckConstraint("image_size IS NULL OR image_size >= 0", name="ck_products_image_size"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(500))
    image_hash: Mapped[str | None] = mapped_column(String(8))
    image_sha256: Mapped[str | None] = mapped_column(String(64))
    image_size: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")


class VendingSlot(TimestampMixin, Base):
    __tablename__ = "vending_slots"
    __table_args__ = (
        UniqueConstraint("device_id", "slot_no", name="uq_vending_slots_device_slot"),
        CheckConstraint("slot_no BETWEEN 1 AND 16", name="ck_vending_slots_slot_no"),
        CheckConstraint("stock >= 0 AND capacity >= 0 AND stock <= capacity", name="ck_vending_slots_stock_capacity"),
        CheckConstraint("servo_type IN ('positional', 'continuous')", name="ck_vending_slots_servo_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), nullable=False)
    slot_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    servo_type: Mapped[str] = mapped_column(String(16), nullable=False, default="positional", server_default="positional")
    home_deg: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    dispense_deg: Mapped[int] = mapped_column(Integer, nullable=False, default=90, server_default="90")
    hold_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=700, server_default="700")
    run_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class CatalogMeta(TimestampMixin, Base):
    __tablename__ = "catalog_meta"
    __table_args__ = (CheckConstraint("version >= 0", name="ck_catalog_meta_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
