"""
Tests for DB-backed store settings (Phase C).

Covers:
  1. First read seeds the singleton row from env (source "database").
  2. Session-less reads work (cache, then env fallback) — the pricing
     helpers and model properties rely on this.
  3. Admin updates take effect immediately (cache invalidated).
  4. Update schema rejects out-of-range values.
  5. Partial updates keep untouched fields.

Run:  PYTHONPATH=. .venv/bin/python -m pytest tests/test_store_settings.py -q
"""
import pytest
from pydantic import ValidationError
from sqlmodel import SQLModel, Session, create_engine

# Import all models so SQLModel.metadata is complete
import app.models  # noqa: F401
from app.core import store_settings as ss
from app.core.config import settings as env_settings
from app.schemas.store_settings import StoreSettingsUpdate


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    ss.invalidate_cache()
    with Session(engine) as s:
        yield s
    ss.invalidate_cache()


def test_1_first_read_seeds_from_env(session):
    snap = ss.get_store_settings(session)
    assert snap.source == "database"
    assert snap.tax_rate == float(env_settings.TAX_RATE)
    assert snap.cod_max_order_value == float(env_settings.COD_MAX_ORDER_VALUE)


def test_2_sessionless_read_matches(session):
    ss.get_store_settings(session)  # warms the cache
    cached = ss.get_store_settings()
    assert cached.tax_rate == float(env_settings.TAX_RATE)


def test_3_update_takes_effect_immediately(session):
    ss.get_store_settings(session)
    row = ss.update_store_settings(session, {"tax_rate": 0.28}, actor_id=None)
    assert row.tax_rate == 0.28
    assert ss.get_store_settings().tax_rate == 0.28
    assert ss.get_store_settings(session).source == "database"


def test_4_partial_update_keeps_rest(session):
    ss.get_store_settings(session)
    ss.update_store_settings(session, {"shipping_cost": 99.0}, actor_id=None)
    snap = ss.get_store_settings(session)
    assert snap.shipping_cost == 99.0
    assert snap.tax_rate == float(env_settings.TAX_RATE)


def test_5_schema_rejects_bad_values():
    with pytest.raises(ValidationError):
        StoreSettingsUpdate(tax_rate=2.0)
    with pytest.raises(ValidationError):
        StoreSettingsUpdate(cod_fee=-5.0)
    with pytest.raises(ValidationError):
        StoreSettingsUpdate(restocking_fee_confirmed=150.0)
    with pytest.raises(ValidationError):
        StoreSettingsUpdate(refund_processing_days=0)
    # Valid partial payload passes.
    assert StoreSettingsUpdate(tax_rate=0.12).tax_rate == 0.12
