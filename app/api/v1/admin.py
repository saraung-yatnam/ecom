from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, require_role
from app.models.user import User, UserRole
from app.repositories import order as order_repo
from app.schemas.order import OrderRead, OrderStatusUpdate, OrderListRead


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.put("/orders/{order_id}/status", response_model=OrderRead)
def update_order_status(
    order_id: UUID,
    status_data: OrderStatusUpdate,
    session: SessionDep,
    current_user: User = Depends(
        require_role(UserRole.manager, UserRole.admin)
    ),
):
    """
    Update order status.
    
    Allowed:
        manager
        admin
    """
    order = order_repo.get_order_by_id(session, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    return order_repo.update_order_status(session, order, status_data.status.value)


@router.get("/orders", response_model=list[OrderListRead])
def get_all_orders(
    session: SessionDep,
    current_user: User = Depends(
        require_role(UserRole.manager, UserRole.admin)
    ),
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
):
    """Get all orders (admin)"""
    orders = order_repo.get_all_orders(session, skip, limit, status)
    
    result = []
    for order in orders:
        order_data = OrderListRead.model_validate(order)
        order_data.item_count = len(order.items) if order.items else 0
        result.append(order_data)
    
    return result