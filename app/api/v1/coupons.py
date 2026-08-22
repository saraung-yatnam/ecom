from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, require_role
from app.models.user import User, UserRole
from app.repositories import coupon as coupon_repo
from app.schemas.coupon import (
    CouponCreate,
    CouponRead,
    CouponUpdate,
    CouponValidateRequest,
    CouponValidateResponse,
)
from app.utils.coupon import validate_coupon, generate_coupon_code


router = APIRouter(prefix="/coupons", tags=["Coupons"])


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
        require_role(UserRole.manager, UserRole.admin)
    ),
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    Get all coupons.
    
    Allowed:
        manager
        admin
    """
    return coupon_repo.get_all_coupons(session, skip, limit, is_active)


@router.get("/{coupon_id}", response_model=CouponRead)
def get_coupon(
    coupon_id: UUID,
    session: SessionDep,
    current_user: User = Depends(
        require_role(UserRole.manager, UserRole.admin)
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
        require_role(UserRole.manager, UserRole.admin)
    ),
):
    """
    Create a new coupon.
    
    Allowed:
        manager
        admin
    """
    # Check if coupon code already exists
    existing = coupon_repo.get_coupon_by_code(session, coupon_data.code)
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Coupon code already exists"
        )
    
    return coupon_repo.create_coupon(
        session,
        coupon_data.model_dump(),
        current_user.id,
    )


@router.put("/{coupon_id}", response_model=CouponRead)
def update_coupon(
    coupon_id: UUID,
    coupon_data: CouponUpdate,
    session: SessionDep,
    current_user: User = Depends(
        require_role(UserRole.manager, UserRole.admin)
    ),
):
    """
    Update a coupon.
    
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
    
    return coupon_repo.update_coupon(
        session,
        coupon,
        coupon_data.model_dump(exclude_unset=True)
    )


@router.delete("/{coupon_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_coupon(
    coupon_id: UUID,
    session: SessionDep,
    current_user: User = Depends(
        require_role(UserRole.manager, UserRole.admin)
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
        require_role(UserRole.manager, UserRole.admin)
    ),
):
    """
    Generate a random coupon code.
    
    Allowed:
        manager
        admin
    """
    return {"code": generate_coupon_code(length)}