from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.api.deps import SessionDep, require_role
from app.models.user import User, UserRole
from app.models.address import Address
from app.models.order import Order
from app.models.cart import Cart
from app.repositories import user as user_repo
from app.schemas.admin import (
    AdminUserListResponse,
    AdminUserRead,
    AdminUserStats,
    AdminUserUpdate,
)

router = APIRouter(prefix="/admin/users", tags=["Admin Users"])


@router.get("", response_model=AdminUserListResponse)
def get_all_users(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1),
    role: UserRole | None = None,
    is_active: bool | None = None,
):
    """
    Get all users (Admin only).
    
    Allowed:
        admin
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
        users=users,
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit,
    )


@router.get("/stats", response_model=AdminUserStats)
def get_user_stats(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """
    Get user statistics (Admin only).
    
    Allowed:
        admin
    """
    return user_repo.get_user_stats(session)


@router.get("/{user_id}", response_model=AdminUserRead)
def get_user(
    user_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """
    Get user by ID (Admin only).
    
    Allowed:
        admin
    """
    user = user_repo.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return user


@router.put("/{user_id}/role", response_model=AdminUserRead)
def update_user_role(
    user_id: UUID,
    update_data: AdminUserUpdate,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """
    Update user role (Admin only).
    
    Allowed:
        admin
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
    
    user = user_repo.update_user_by_admin(
        session,
        user,
        update_data.model_dump(exclude_unset=True)
    )
    
    return user


@router.put("/{user_id}/status", response_model=AdminUserRead)
def update_user_status(
    user_id: UUID,
    update_data: AdminUserUpdate,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """
    Update user status (active/inactive) (Admin only).
    
    Allowed:
        admin
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
    
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """
    Delete user (Admin only).
    
    Allowed:
        admin
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