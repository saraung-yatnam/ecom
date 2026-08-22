from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session, select

from app.models.coupon import Coupon


def create_coupon(
    session: Session,
    coupon_data: dict,
    created_by: UUID,
) -> Coupon:
    """Create a new coupon"""
    coupon = Coupon(
        **coupon_data,
        created_by=created_by,
        times_used=0,
    )
    session.add(coupon)
    session.commit()
    session.refresh(coupon)
    return coupon


def get_coupon_by_id(
    session: Session,
    coupon_id: UUID,
) -> Coupon | None:
    """Get coupon by ID"""
    return session.get(Coupon, coupon_id)


def get_coupon_by_code(
    session: Session,
    code: str,
) -> Coupon | None:
    """Get coupon by code"""
    statement = select(Coupon).where(Coupon.code == code)
    return session.exec(statement).first()


def get_all_coupons(
    session: Session,
    skip: int = 0,
    limit: int = 100,
    is_active: bool | None = None,
) -> list[Coupon]:
    """Get all coupons"""
    statement = select(Coupon).order_by(Coupon.created_at.desc())
    
    if is_active is not None:
        statement = statement.where(Coupon.is_active == is_active)
    
    statement = statement.offset(skip).limit(limit)
    return session.exec(statement).all()


def update_coupon(
    session: Session,
    coupon: Coupon,
    coupon_data: dict,
) -> Coupon:
    """Update coupon"""
    for key, value in coupon_data.items():
        if value is not None:
            setattr(coupon, key, value)
    
    coupon.updated_at = datetime.now(timezone.utc)
    session.add(coupon)
    session.commit()
    session.refresh(coupon)
    return coupon


def delete_coupon(
    session: Session,
    coupon: Coupon,
) -> None:
    """Delete coupon"""
    session.delete(coupon)
    session.commit()


def increment_coupon_usage(
    session: Session,
    coupon: Coupon,
) -> Coupon:
    """Increment coupon usage count"""
    coupon.times_used += 1
    session.add(coupon)
    session.commit()
    session.refresh(coupon)
    return coupon


def get_user_coupon_usage_count(
    session: Session,
    coupon_code: str,
    user_id: UUID,
) -> int:
    """Get how many times a user has used a coupon"""
    from app.models.order import Order
    
    statement = select(Order).where(
        Order.coupon_code == coupon_code,
        Order.user_id == user_id,
    )
    orders = session.exec(statement).all()
    return len(orders)