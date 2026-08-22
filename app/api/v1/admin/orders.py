from uuid import UUID
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.api.deps import SessionDep, require_role
from app.models.user import User, UserRole
from app.repositories import order as order_repo
from app.schemas.order import OrderRead, OrderStatusUpdate, OrderListRead
from app.services.email_service import email_service
from app.core.config import settings

router = APIRouter(prefix="/admin/orders", tags=["Admin Orders"])


@router.get("", response_model=dict)
def get_all_orders_admin(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    search: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
):
    """
    Get all orders with filters and pagination.
    
    Allowed:
        manager
        admin
    """
    skip = (page - 1) * limit
    
    orders, total = order_repo.get_all_orders_with_filters(
        session=session,
        skip=skip,
        limit=limit,
        status=status,
        search=search,
        from_date=from_date,
        to_date=to_date,
    )
    
    return {
        "orders": orders,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit,
        }
    }


@router.get("/stats", response_model=dict)
def get_order_stats(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """
    Get order statistics.
    
    Allowed:
        manager
        admin
    """
    return order_repo.get_order_statistics(session)


@router.get("/{order_id}", response_model=OrderRead)
def get_order_detail(
    order_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """
    Get detailed order information.
    
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
    
    return order


@router.put("/{order_id}/status", response_model=OrderRead)
def update_order_status_admin(
    order_id: UUID,
    status_data: OrderStatusUpdate,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
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
    
    old_status = order.status
    new_status = status_data.status.value
    order = order_repo.update_order_status(session, order, new_status)
    
    # Send email notification on status change
    if settings.SENDGRID_API_KEY:
        try:
            user = session.get(User, order.user_id)
            if user:
                if new_status == "shipped" and old_status != "shipped":
                    email_service.send_order_shipped(order, user)
                    print(f"Order shipped email sent to {user.email}")
                elif new_status == "delivered" and old_status != "delivered":
                    email_service.send_order_delivered(order, user)
                    print(f"Order delivered email sent to {user.email}")
                elif new_status == "cancelled" and old_status != "cancelled":
                    email_service.send_order_cancelled(order, user)
                    print(f"Order cancelled email sent to {user.email}")
                elif new_status == "refunded" and old_status != "refunded":
                    email_service.send_order_refunded(order, user)
                    print(f"Order refunded email sent to {user.email}")
        except Exception as e:
            print(f"Failed to send order status email: {str(e)}")
    
    return order