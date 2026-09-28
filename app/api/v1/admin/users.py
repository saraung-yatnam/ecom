from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.api.deps import SessionDep, require_perm
from app.models.user import User
from app.models.address import Address
from app.models.order import Order
from app.models.cart import Cart
from app.repositories import user as user_repo
from app.repositories import rbac as rbac_repo
from app.repositories import order as order_repo
from app.repositories import address as address_repo
from app.schemas.admin import (
    AdminUserListResponse,
    AdminUserRead,
    AdminUserOrderStats,
    AdminUserStats,
    AdminUserUpdate,
)
from app.schemas.address import AddressRead

router = APIRouter(prefix="/admin/users", tags=["Admin Users"])


def _admin_user_read(session: SessionDep, user: User) -> dict:
    """AdminUserRead payload enriched with dynamic roles/permissions."""
    data = AdminUserRead.model_validate(user).model_dump()
    try:
        data.update(rbac_repo.user_security_profile(session, user))
    except Exception:
        legacy = getattr(user.role, "value", user.role) or "customer"
        data.update({"roles": [str(legacy)], "permissions": []})
    return data


@router.get("", response_model=AdminUserListResponse)
def get_all_users(
    session: SessionDep,
    current_user: User = Depends(require_perm("users.view")),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1),
    role: str | None = None,
    is_active: bool | None = None,
):
    """
    Get all users (requires users.view permission).

    The ``role`` filter accepts a legacy role (admin/manager/staff/
    customer) or any dynamic role slug (e.g. "packer").
    """
    skip = (page - 1) * limit
    
    users, total = user_repo.get_all_users(
        session=session,
        skip=skip,
        limit=limit,
        search=search,
        role=role,
        is_active=is_active,
    )
    
    return AdminUserListResponse(
        users=[_admin_user_read(session, u) for u in users],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit,
    )


@router.get("/stats", response_model=AdminUserStats)
def get_user_stats(
    session: SessionDep,
    current_user: User = Depends(require_perm("users.view")),
):
    """
    Get user statistics (requires users.view permission).
    """
    return user_repo.get_user_stats(session)


@router.get("/{user_id}/stats", response_model=AdminUserOrderStats)
def get_user_order_stats(
    user_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_perm("users.view")),
):
    """
    Get lifetime order statistics for a single user.

    Returns total orders, total spent, last order, average order value,
    items purchased, per-status breakdown, etc.
    """
    user = user_repo.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    stats = order_repo.get_user_order_statistics(session, user_id)
    stats["user_id"] = user_id
    return stats


@router.get("/{user_id}/addresses", response_model=list[AddressRead])
def get_user_addresses(
    user_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_perm("users.view")),
):
    """
    Get all addresses for a specific user (Admin only).

    Unlike the customer-facing `GET /addresses` (which ONLY returns the
    current user's own addresses), this lets a staff member with users.view
    see any user's saved addresses from the user detail page.
    """
    user = user_repo.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    addresses = address_repo.get_addresses_by_user(session, user_id)
    return [
        AddressRead(
            id=addr.id,
            user_id=addr.user_id,
            label=addr.label,
            line1=addr.line1,
            line2=addr.line2,
            city=addr.city,
            state=addr.state,
            postal_code=addr.postal_code,
            country=addr.country,
            is_default=addr.is_default,
            created_at=addr.created_at,
        )
        for addr in addresses
    ]


@router.get("/{user_id}", response_model=AdminUserRead)
def get_user(
    user_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_perm("users.view")),
):
    """
    Get user by ID (requires users.view permission).
    """
    user = user_repo.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return _admin_user_read(session, user)


@router.put("/{user_id}/role", response_model=AdminUserRead)
def update_user_role(
    user_id: UUID,
    update_data: AdminUserUpdate,
    session: SessionDep,
    current_user: User = Depends(require_perm("users.manage_roles")),
):
    """
    Update user role (requires users.manage_roles permission).

    Legacy compat: accepts ``{role: "<slug>"}`` and assigns the matching
    dynamic role. Prefer ``PUT /admin/users/{id}/roles`` for multi-role
    assignment.
    """
    user = user_repo.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent admin from changing their own role
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role"
        )

    payload = update_data.model_dump(exclude_unset=True)
    if payload.get("role") is not None:
        slug = getattr(payload["role"], "value", payload["role"])
        role = rbac_repo.get_role_by_slug(session, str(slug))
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown role: {slug}",
            )
        rbac_repo.set_user_roles(
            session, user, [role], assigned_by=current_user.id
        )
        payload.pop("role")
    if payload:
        user = user_repo.update_user_by_admin(session, user, payload)

    return _admin_user_read(session, user)


@router.put("/{user_id}/status", response_model=AdminUserRead)
def update_user_status(
    user_id: UUID,
    update_data: AdminUserUpdate,
    session: SessionDep,
    current_user: User = Depends(require_perm("users.manage")),
):
    """
    Update user status (active/inactive) (requires users.manage permission).
    """
    user = user_repo.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent admin from deactivating themselves
    if user.id == current_user.id and update_data.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account"
        )
    
    user = user_repo.update_user_by_admin(
        session,
        user,
        update_data.model_dump(exclude_unset=True)
    )
    
    return _admin_user_read(session, user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_perm("users.manage")),
):
    """
    Delete user (requires users.manage permission).
    """
    user = user_repo.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Prevent admin from deleting themselves
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    # 👇 Check if user has related data
    # Check for addresses
    addresses = session.exec(select(Address).where(Address.user_id == user_id)).all()
    if addresses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete user. They have {len(addresses)} address(es) associated with them."
        )
    
    # Check for orders
    orders = session.exec(select(Order).where(Order.user_id == user_id)).all()
    if orders:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete user. They have {len(orders)} order(s) associated with them."
        )
    
    # Check for cart
    cart = session.exec(select(Cart).where(Cart.user_id == user_id)).first()
    if cart:
        # Clear cart first
        cart.user_id = None
        session.add(cart)
        session.commit()
    
    user_repo.delete_user(session, user)
    return None 