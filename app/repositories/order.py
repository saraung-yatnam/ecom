from datetime import datetime, timedelta, timezone
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlmodel import Session

from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User
from app.models.address import Address  # Add this if you have address model


def get_order_by_id(session: Session, order_id: UUID) -> Order | None:
    """Get order by ID with items and user loaded"""
    statement = (
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.items),
            selectinload(Order.user),  # 👈 Add this
            selectinload(Order.shipping_address),  # 👈 Add this
            selectinload(Order.billing_address),   # 👈 Add this
        )
    )
    result = session.execute(statement)
    return result.scalar_one_or_none()


def get_orders_by_user(
    session: Session,
    user_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> list[Order]:
    """Get all orders for a user"""
    statement = (
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.placed_at.desc())
        .offset(skip)
        .limit(limit)
        .options(
            selectinload(Order.items),
            selectinload(Order.shipping_address),
        )
    )
    result = session.execute(statement)
    return result.scalars().all()


def get_order_by_number(session: Session, order_number: str) -> Order | None:
    """Get order by order number"""
    statement = (
        select(Order)
        .where(Order.order_number == order_number)
        .options(
            selectinload(Order.items),
            selectinload(Order.user),
            selectinload(Order.shipping_address),
        )
    )
    result = session.execute(statement)
    return result.scalar_one_or_none()


def get_all_orders(
    session: Session,
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
) -> list[Order]:
    """Get all orders (admin)"""
    statement = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.user),  # 👈 Add this
        selectinload(Order.shipping_address),  # 👈 Add this
    )
    
    if status:
        statement = statement.where(Order.status == status)
    
    statement = statement.order_by(Order.placed_at.desc())
    statement = statement.offset(skip).limit(limit)
    
    result = session.execute(statement)
    return result.scalars().all()


def update_order_status(
    session: Session,
    order: Order,
    status: str,
) -> Order:
    """Update order status"""
    order.status = status
    
    # Auto-update timestamps
    if status == "shipped":
        order.shipped_at = datetime.now(timezone.utc)
    elif status == "delivered":
        order.delivered_at = datetime.now(timezone.utc)
    
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


# =========================================================
# ADMIN FUNCTIONS
# =========================================================

def get_order_statistics(session: Session) -> dict:
    """Get order statistics"""
    total_orders = session.execute(select(func.count()).select_from(Order)).scalar() or 0
    
    pending_orders = session.execute(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.PENDING)
    ).scalar() or 0
    
    confirmed_orders = session.execute(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.CONFIRMED)
    ).scalar() or 0
    
    shipped_orders = session.execute(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.SHIPPED)
    ).scalar() or 0
    
    delivered_orders = session.execute(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.DELIVERED)
    ).scalar() or 0
    
    cancelled_orders = session.execute(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.CANCELLED)
    ).scalar() or 0
    
    refunded_orders = session.execute(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.REFUNDED)
    ).scalar() or 0
    
    return {
        "total": total_orders,
        "pending": pending_orders,
        "confirmed": confirmed_orders,
        "shipped": shipped_orders,
        "delivered": delivered_orders,
        "cancelled": cancelled_orders,
        "refunded": refunded_orders,
    }


def get_recent_orders(session: Session, limit: int = 10) -> list[Order]:
    """Get recent orders with user data"""
    statement = (
        select(Order)
        .order_by(Order.placed_at.desc())
        .limit(limit)
        .options(
            selectinload(Order.user),  # 👈 Add this
            selectinload(Order.shipping_address),  # 👈 Add this
            selectinload(Order.items),  # 👈 Add this
        )
    )
    result = session.execute(statement)
    return result.scalars().all()


def get_all_orders_with_filters(
    session: Session,
    skip: int = 0,
    limit: int = 20,
    status: str | None = None,
    search: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[list[Order], int]:
    """Get all orders with filters and user data"""
    # Build base query with eager loading
    statement = select(Order).options(
        selectinload(Order.items),  # 👈 Keep this
        selectinload(Order.user),  # 👈 ADD THIS - loads user data
        selectinload(Order.shipping_address),  # 👈 ADD THIS - loads shipping address
        selectinload(Order.billing_address),   # 👈 ADD THIS - loads billing address
    )
    
    # Apply filters
    if status:
        statement = statement.where(Order.status == status)
    
    if search:
        # Search by order number or customer name/email
        statement = statement.where(
            (Order.order_number.ilike(f"%{search}%")) |
            (Order.user.has(User.full_name.ilike(f"%{search}%"))) |
            (Order.user.has(User.email.ilike(f"%{search}%")))
        )
    
    if from_date:
        statement = statement.where(Order.placed_at >= from_date)
    
    if to_date:
        statement = statement.where(Order.placed_at <= to_date)
    
    # Get total count
    count_statement = select(func.count()).select_from(statement.subquery())
    total = session.execute(count_statement).scalar() or 0
    
    # Get paginated results
    statement = statement.order_by(Order.placed_at.desc()).offset(skip).limit(limit)
    result = session.execute(statement)
    orders = result.scalars().all()
    
    return orders, total


def get_order_summary(session: Session) -> dict:
    """Get order summary for admin dashboard"""
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    
    # Today's orders
    today_orders = session.execute(
        select(func.count(Order.id)).where(func.date(Order.placed_at) == today)
    ).scalar() or 0
    
    # This week's orders
    week_orders = session.execute(
        select(func.count(Order.id)).where(Order.placed_at >= start_of_week)
    ).scalar() or 0
    
    # This month's orders
    month_orders = session.execute(
        select(func.count(Order.id)).where(Order.placed_at >= start_of_month)
    ).scalar() or 0
    
    return {
        "today": today_orders,
        "this_week": week_orders,
        "this_month": month_orders,
    }