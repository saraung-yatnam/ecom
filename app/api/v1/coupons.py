from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, require_perm
from app.models.category import Category
from app.models.coupon import CouponType, TriggerType
from app.models.user import User
from app.repositories import coupon as coupon_repo
from app.schemas.coupon import (
    CouponCreate,
    CouponRead,
    CouponUpdate,
    CouponValidateRequest,
    CouponValidateResponse,
    validate_trigger_config,
)
from app.utils.coupon import generate_coupon_code


router = APIRouter(prefix="/coupons", tags=["Coupons"])


def _enum_value(field) -> str:
    """Normalize enum members / plain strings to their value."""
    return str(getattr(field, "value", field))


# =========================================================
# PUBLIC ENDPOINTS
# =========================================================

@router.post("/validate", response_model=CouponValidateResponse)
def validate_coupon_public(
    request: CouponValidateRequest,
    session: SessionDep,
):
    """
    Validate coupon code (public).
    Check if coupon exists and is valid.
    """
    coupon = coupon_repo.get_coupon_by_code(session, request.code)
    if not coupon:
        return CouponValidateResponse(
            valid=False,
            message="Coupon not found"
        )
    
    # Automatic coupons cannot be typed in — they apply themselves.
    if coupon.coupon_type == CouponType.AUTOMATIC:
        return CouponValidateResponse(
            valid=False,
            is_automatic=True,
            message=(
                "This coupon is applied automatically when the offer conditions "
                "are met — no code needed"
            ),
            discount_type=coupon.discount_type,
            value=coupon.value,
        )
    
    return CouponValidateResponse(
        valid=True,
        message="Coupon is valid",
        discount_type=coupon.discount_type,
        value=coupon.value,
        min_order_value=coupon.min_order_value,
    )


# =========================================================
# ADMIN ENDPOINTS
# =========================================================

@router.get("", response_model=list[CouponRead])
def get_coupons(
    session: SessionDep,
    current_user: User = Depends(
        require_perm("coupons.view")
    ),
    is_active: bool | None = None,
    coupon_type: CouponType | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    Get all coupons.
    
    Allowed:
        manager
        admin
    """
    return coupon_repo.get_all_coupons(session, skip, limit, is_active, coupon_type)


@router.get("/{coupon_id}", response_model=CouponRead)
def get_coupon(
    coupon_id: UUID,
    session: SessionDep,
    current_user: User = Depends(
        require_perm("coupons.view")
    ),
):
    """
    Get coupon by ID.
    
    Allowed:
        manager
        admin
    """
    coupon = coupon_repo.get_coupon_by_id(session, coupon_id)
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    return coupon


@router.post("", response_model=CouponRead, status_code=status.HTTP_201_CREATED)
def create_coupon(
    coupon_data: CouponCreate,
    session: SessionDep,
    current_user: User = Depends(
        require_perm("coupons.manage")
    ),
):
    """
    Create a new coupon (manual or automatic).
    
    For AUTOMATIC coupons the code is generated server-side when it is not
    provided (AUTO-XXXXXX) — customers never type it.
    
    Allowed:
        manager
        admin
    """
    # Check if a provided coupon code already exists
    if coupon_data.code:
        existing = coupon_repo.get_coupon_by_code(session, coupon_data.code)
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Coupon code already exists"
            )
    
    create_data = coupon_data.model_dump()
    
    # Automatic coupons get a unique server-generated code when none was sent
    if (
        coupon_data.coupon_type == CouponType.AUTOMATIC
        and not create_data.get("code")
    ):
        create_data["code"] = coupon_repo.get_next_automatic_code(session)
    
    # Make sure the trigger category actually exists
    if create_data.get("trigger_category_id") is not None:
        if not session.get(Category, create_data["trigger_category_id"]):
            raise HTTPException(
                status_code=400,
                detail="Trigger category not found"
            )
    
    return coupon_repo.create_coupon(
        session,
        create_data,
        current_user.id,
    )


@router.put("/{coupon_id}", response_model=CouponRead)
def update_coupon(
    coupon_id: UUID,
    coupon_data: CouponUpdate,
    session: SessionDep,
    current_user: User = Depends(
        require_perm("coupons.manage")
    ),
):
    """
    Update a coupon (including type/trigger changes).
    
    Allowed:
        manager
        admin
    """
    coupon = coupon_repo.get_coupon_by_id(session, coupon_id)
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    
    # If code is being changed, check uniqueness
    if coupon_data.code and coupon_data.code != coupon.code:
        existing = coupon_repo.get_coupon_by_code(session, coupon_data.code)
        if existing and existing.id != coupon.id:
            raise HTTPException(
                status_code=400,
                detail="Coupon code already exists"
            )
    
    update_data = coupon_data.model_dump(exclude_unset=True)
    none_fields: list[str] = []
    
    new_coupon_type = update_data.get("coupon_type")
    new_trigger = update_data.get("trigger_type")
    
    # Switching to MANUAL clears any trigger configuration
    if (
        new_coupon_type is not None
        and _enum_value(new_coupon_type) == CouponType.MANUAL.value
    ):
        update_data["trigger_type"] = TriggerType.NONE
        none_fields = [
            "trigger_min_cart_value",
            "trigger_min_item_count",
            "trigger_category_id",
            "trigger_category_spend",
        ]
    elif new_trigger is not None:
        old_trigger = _enum_value(coupon.trigger_type)
        if _enum_value(new_trigger) != old_trigger:
            # Trigger type changed — clear stale payload first; a new payload
            # sent in this same request is applied after (repo sets non-None
            # values after none_fields).
            none_fields = [
                "trigger_min_cart_value",
                "trigger_min_item_count",
                "trigger_category_id",
                "trigger_category_spend",
            ]
    
    # Validate the MERGED result so a partial update can't create a broken
    # configuration (e.g. an automatic coupon without a complete trigger).
    validate_trigger_config(
        coupon_type=update_data.get("coupon_type", coupon.coupon_type),
        trigger_type=update_data.get("trigger_type", coupon.trigger_type),
        code=update_data.get("code", coupon.code),
        trigger_min_cart_value=update_data.get(
            "trigger_min_cart_value", coupon.trigger_min_cart_value
        ),
        trigger_min_item_count=update_data.get(
            "trigger_min_item_count", coupon.trigger_min_item_count
        ),
        trigger_category_id=update_data.get(
            "trigger_category_id", coupon.trigger_category_id
        ),
        trigger_category_spend=update_data.get(
            "trigger_category_spend", coupon.trigger_category_spend
        ),
    )
    
    # Make sure the trigger category exists when one is being set
    if update_data.get("trigger_category_id") is not None:
        if not session.get(Category, update_data["trigger_category_id"]):
            raise HTTPException(
                status_code=400,
                detail="Trigger category not found"
            )
    
    return coupon_repo.update_coupon(
        session,
        coupon,
        update_data,
        none_fields,
    )


@router.delete("/{coupon_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_coupon(
    coupon_id: UUID,
    session: SessionDep,
    current_user: User = Depends(
        require_perm("coupons.manage")
    ),
):
    """
    Delete a coupon.
    
    Allowed:
        manager
        admin
    """
    coupon = coupon_repo.get_coupon_by_id(session, coupon_id)
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    
    coupon_repo.delete_coupon(session, coupon)
    return None


@router.post("/generate", response_model=dict)
def generate_coupon(
    length: int = 8,
    current_user: User = Depends(
        require_perm("coupons.manage")
    ),
):
    """
    Generate a random coupon code (manual coupons).
    
    Allowed:
        manager
        admin
    """
    return {"code": generate_coupon_code(length)}
