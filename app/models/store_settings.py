# app/models/store_settings.py
"""Single-row store policy table (tax, shipping, COD, refunds, expiry).

These knobs used to live only in env vars, so every price tweak needed a
deploy. The row is seeded from the env on first read; the admin Store
settings page edits it afterwards. Hot paths read through the cached
snapshot in ``app.core.store_settings`` (60s TTL) — never per-request SQL.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Field, SQLModel


class StoreSettings(SQLModel, table=True):
    __tablename__ = "store_settings"

    # Singleton row — id is always 1.
    id: int = Field(default=1, primary_key=True)

    # Tax & pricing
    tax_rate: float = Field(default=0.18)

    # Shipping
    free_shipping_threshold: float = Field(default=1000.00)
    shipping_cost: float = Field(default=50.00)

    # COD
    cod_fee: float = Field(default=50.00)
    cod_min_order_value: float = Field(default=0.00)
    cod_max_order_value: float = Field(default=10000.00)

    # Cancellations & refunds (percent fees + customer-facing days)
    restocking_fee_pending: float = Field(default=0.0)
    restocking_fee_confirmed: float = Field(default=5.0)
    restocking_fee_processing: float = Field(default=15.0)
    refund_processing_days: int = Field(default=5)

    # Abandoned unpaid online orders (auto-cancel sweep)
    pending_order_expiry_minutes: int = Field(default=30)

    updated_by: UUID | None = Field(default=None, foreign_key="users.id")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
