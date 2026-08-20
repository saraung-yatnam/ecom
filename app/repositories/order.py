from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.order import Order, OrderItem


def get_order_by_id(session: Session, order_id: UUID) -> Order | None:
    """Get order by ID with items loaded"""
    statement = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
    )
    return session.exec(statement).first()


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
        .options(selectinload(Order.items))
    )
    return session.exec(statement).all()


def get_order_by_number(session: Session, order_number: str) -> Order | None:
    """Get order by order number"""
    statement = (
        select(Order)
        .where(Order.order_number == order_number)
        .options(selectinload(Order.items))
    )
    return session.exec(statement).first()


def get_all_orders(
    session: Session,
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
) -> list[Order]:
    """Get all orders (admin)"""
    statement = select(Order).options(selectinload(Order.items))
    
    if status:
        statement = statement.where(Order.status == status)
    
    statement = statement.order_by(Order.placed_at.desc())
    statement = statement.offset(skip).limit(limit)
    
    return session.exec(statement).all()


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