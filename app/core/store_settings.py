# app/core/store_settings.py
"""DB-backed store policy with env fallback and a short-TTL memory cache.

Why this shape: pricing helpers (``app/utils/cart.py``), the pricing
engine (``app/services/pricing.py``) and model properties
(``Order.restocking_fee_percentage``) all run WITHOUT a DB session, so
they cannot query per call. They read :func:`get_store_settings` with no
arguments and get the cached snapshot (refreshed from the DB at most
every ``TTL_SECONDS``). Request handlers with a session pass it in for a
guaranteed-fresh read. Multi-worker staleness is bounded by the TTL.

Env vars remain the boot defaults: a fresh database is seeded from them
on first read, and if the table is unreachable the snapshot is pure env.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.config import settings

TTL_SECONDS = 60.0

_CACHE: dict = {"snapshot": None, "expires_at": 0.0}


@dataclass(frozen=True)
class StoreSettingsSnapshot:
    """Plain (detached-safe) copy of the policy row.

    ``source`` is "database" once an admin has saved (or the env seed ran),
    "environment" when the table is missing/unreachable.
    """

    tax_rate: float = 0.18
    free_shipping_threshold: float = 1000.00
    shipping_cost: float = 50.00
    cod_fee: float = 50.00
    cod_min_order_value: float = 0.00
    cod_max_order_value: float = 10000.00
    restocking_fee_pending: float = 0.0
    restocking_fee_confirmed: float = 5.0
    restocking_fee_processing: float = 15.0
    refund_processing_days: int = 5
    pending_order_expiry_minutes: int = 30
    source: str = "environment"


def _snapshot_from_env() -> StoreSettingsSnapshot:
    return StoreSettingsSnapshot(
        tax_rate=float(settings.TAX_RATE),
        free_shipping_threshold=float(settings.FREE_SHIPPING_THRESHOLD),
        shipping_cost=float(settings.SHIPPING_COST),
        cod_fee=float(settings.COD_FEE),
        cod_min_order_value=float(settings.COD_MIN_ORDER_VALUE),
        cod_max_order_value=float(settings.COD_MAX_ORDER_VALUE),
        restocking_fee_pending=float(settings.RESTOCKING_FEE_PENDING),
        restocking_fee_confirmed=float(settings.RESTOCKING_FEE_CONFIRMED),
        restocking_fee_processing=float(settings.RESTOCKING_FEE_PROCESSING),
        refund_processing_days=int(settings.REFUND_PROCESSING_DAYS),
        pending_order_expiry_minutes=int(settings.PENDING_ORDER_EXPIRY_MINUTES),
        source="environment",
    )


def _snapshot_from_row(row) -> StoreSettingsSnapshot:
    return StoreSettingsSnapshot(
        tax_rate=float(row.tax_rate),
        free_shipping_threshold=float(row.free_shipping_threshold),
        shipping_cost=float(row.shipping_cost),
        cod_fee=float(row.cod_fee),
        cod_min_order_value=float(row.cod_min_order_value),
        cod_max_order_value=float(row.cod_max_order_value),
        restocking_fee_pending=float(row.restocking_fee_pending),
        restocking_fee_confirmed=float(row.restocking_fee_confirmed),
        restocking_fee_processing=float(row.restocking_fee_processing),
        refund_processing_days=int(row.refund_processing_days),
        pending_order_expiry_minutes=int(row.pending_order_expiry_minutes),
        source="database",
    )


def _cached() -> StoreSettingsSnapshot | None:
    if time.monotonic() < _CACHE["expires_at"]:
        return _CACHE["snapshot"]
    return None


def _store(snapshot: StoreSettingsSnapshot) -> StoreSettingsSnapshot:
    _CACHE["snapshot"] = snapshot
    _CACHE["expires_at"] = time.monotonic() + TTL_SECONDS
    return snapshot


def invalidate_cache() -> None:
    """Force the next read to hit the database (or env)."""
    _CACHE["snapshot"] = None
    _CACHE["expires_at"] = 0.0


def ensure_store_settings(session):
    """Return the singleton row, seeding it from env on first use.

    Commits the seed so concurrent workers converge on one row.
    """
    from app.models.store_settings import StoreSettings

    row = session.get(StoreSettings, 1)
    if row is None:
        env = _snapshot_from_env()
        row = StoreSettings(
            id=1,
            tax_rate=env.tax_rate,
            free_shipping_threshold=env.free_shipping_threshold,
            shipping_cost=env.shipping_cost,
            cod_fee=env.cod_fee,
            cod_min_order_value=env.cod_min_order_value,
            cod_max_order_value=env.cod_max_order_value,
            restocking_fee_pending=env.restocking_fee_pending,
            restocking_fee_confirmed=env.restocking_fee_confirmed,
            restocking_fee_processing=env.restocking_fee_processing,
            refund_processing_days=env.refund_processing_days,
            pending_order_expiry_minutes=env.pending_order_expiry_minutes,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def refresh_store_settings(session) -> StoreSettingsSnapshot:
    """Re-read the row and recache. Called after every admin save."""
    invalidate_cache()
    return _store(_snapshot_from_row(ensure_store_settings(session)))


def get_store_settings(session=None) -> StoreSettingsSnapshot:
    """Cached snapshot; session callers get a guaranteed-fresh read.

    Session-less callers (pricing helpers, model properties) get the cache
    or env defaults — never SQL.
    """
    hit = _cached()
    if hit is not None:
        return hit
    if session is None:
        return _store(_snapshot_from_env())
    try:
        return _store(_snapshot_from_row(ensure_store_settings(session)))
    except Exception:
        return _store(_snapshot_from_env())


def update_store_settings(session, data: dict, actor_id=None):
    """Apply an admin save (validated upstream), recache, return the row."""
    from app.models.store_settings import StoreSettings

    row = ensure_store_settings(session)
    for key, value in data.items():
        if value is not None and hasattr(row, key):
            setattr(row, key, value)
    from datetime import datetime, timezone

    row.updated_by = actor_id
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    refresh_store_settings(session)
    return row
