# app/api/v1/admin/settings.py
"""Admin store-policy settings (requires settings.manage — admins only).

Reads/writes the singleton ``store_settings`` row that replaced the
env-only knobs (tax, shipping, COD, restocking fees, expiry). Every save
refreshes the in-process cache immediately and writes an audit entry with
the before/after diff — money-rule changes must always have a trail.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import SessionDep, require_perm
from app.core.store_settings import (
    ensure_store_settings,
    get_store_settings,
    update_store_settings,
)
from app.models.user import User
from app.repositories import audit as audit_repo
from app.schemas.store_settings import StoreSettingsRead, StoreSettingsUpdate

router = APIRouter(prefix="/admin/settings", tags=["Admin Settings"])

_READABLE = (
    "tax_rate",
    "free_shipping_threshold",
    "shipping_cost",
    "cod_fee",
    "cod_min_order_value",
    "cod_max_order_value",
    "restocking_fee_pending",
    "restocking_fee_confirmed",
    "restocking_fee_processing",
    "refund_processing_days",
    "pending_order_expiry_minutes",
)


def _read_model(session: SessionDep) -> StoreSettingsRead:
    snap = get_store_settings(session)
    row = ensure_store_settings(session)
    data = {key: getattr(snap, key) for key in _READABLE}
    return StoreSettingsRead(
        **data,
        source=snap.source,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


@router.get("/store", response_model=StoreSettingsRead)
def get_store_policy(
    session: SessionDep,
    current_user: User = Depends(require_perm("settings.manage")),
):
    """Current store policy + where it came from (database vs env)."""
    return _read_model(session)


@router.put("/store", response_model=StoreSettingsRead)
def update_store_policy(
    payload: StoreSettingsUpdate,
    request: Request,
    session: SessionDep,
    current_user: User = Depends(require_perm("settings.manage")),
):
    """Save store policy. Partial update — omitted fields keep their value."""
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nothing to update",
        )
    if (
        "cod_min_order_value" in data
        or "cod_max_order_value" in data
    ):
        before = get_store_settings(session)
        lo = data.get("cod_min_order_value", before.cod_min_order_value)
        hi = data.get("cod_max_order_value", before.cod_max_order_value)
        if hi < lo:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cod_max_order_value must be >= cod_min_order_value",
            )

    before = {key: getattr(get_store_settings(session), key) for key in data}
    row = update_store_settings(session, data, actor_id=current_user.id)
    after = {key: getattr(row, key) for key in data}
    audit_repo.log_and_commit(
        session,
        action="settings.store_updated",
        entity="settings",
        entity_id=None,
        actor_id=current_user.id,
        before=before,
        after=after,
        ip_address=audit_repo.client_ip(request),
    )
    return _read_model(session)
