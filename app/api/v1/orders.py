from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, get_current_user
from app.models.user import User
from app.repositories import order as order_repo
from app.schemas.order import OrderRead


router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("", response_model=list[OrderRead])
def get_orders(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 20,
):
    """Get all orders for current user"""
    return order_repo.get_orders_by_user(session, current_user.id, skip, limit)


@router.get("/{order_id}", response_model=OrderRead)
def get_order(
    order_id: UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Get specific order by ID"""
    order = order_repo.get_order_by_id(session, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return order


@router.get("/number/{order_number}", response_model=OrderRead)
def get_order_by_number(
    order_number: str,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Get specific order by order number"""
    order = order_repo.get_order_by_number(session, order_number)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return order