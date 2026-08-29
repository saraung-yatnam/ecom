# app/api/v1/admin/cod.py
"""
Admin endpoints for Cash on Delivery (COD) orders.

COD lifecycle:
  checkout (payment_method=cod) -> order.status=confirmed, payment_status="cod_pending"
  cash collected on delivery    -> POST /admin/cod/orders/{id}/collect
                                -> payment_status="paid" + COD payment record created
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlmodel import Session

from app.api.deps import SessionDep, require_role
from app.models.user import User, UserRole
from app.models.order import Order
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.repositories import order as order_repo

router = APIRouter(prefix="/admin/cod", tags=["Admin COD"])


@router.get("/pending")
def get_pending_cod_orders(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """
    List all COD orders waiting for cash collection.
    
    Allowed:
        manager
        admin
    """
    statement = (
        select(Order)
        .where(Order.payment_method == "cod")
        .where(Order.payment_status == "cod_pending")
        .order_by(Order.placed_at.desc())
        .options(
            selectinload(Order.user),
            selectinload(Order.items),
        )
    )
    orders = session.execute(statement).scalars().all()

    return {
        "count": len(orders),
        "total_pending_amount": float(sum(o.grand_total for o in orders)),
        "orders": [
            {
                "id": str(o.id),
                "order_number": o.order_number,
                "customer": {
                    "id": str(o.user.id),
                    "full_name": o.user.full_name,
                    "email": o.user.email,
                    "phone": o.user.phone,
                } if o.user else None,
                "grand_total": float(o.grand_total),
                "cod_fee": float(o.cod_fee or 0),
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "payment_status": o.payment_status,
                "placed_at": o.placed_at.isoformat() if o.placed_at else None,
            }
            for o in orders
        ],
    }


@router.post("/orders/{order_id}/collect", status_code=status.HTTP_200_OK)
def collect_cod_payment(
    order_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """
    Mark a COD order's cash as COLLECTED ON DELIVERY.
    
    - Creates a COD payment record (status=succeeded)
    - Flips the order to payment_status="paid"
    
    Allowed:
        manager
        admin
    """
    order = order_repo.get_order_by_id(session, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.payment_method != "cod":
        raise HTTPException(
            status_code=400,
            detail="Order was not placed with Cash on Delivery",
        )
    
    if order.payment_status == "paid":
        raise HTTPException(status_code=400, detail="COD payment already collected")
    
    if order.payment_status != "cod_pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot collect COD for order with payment_status '{order.payment_status}'",
        )
    
    order_status_value = getattr(order.status, "value", order.status)
    if order_status_value == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot collect COD for a cancelled order")
    
    # Record the cash collection as a real payment (audit trail + analytics)
    now = datetime.now(timezone.utc)
    payment = Payment(
        order_id=order.id,
        provider=PaymentProvider.COD,
        provider_payment_id=f"cod_{order.order_number}",
        amount=order.grand_total,
        currency="INR",
        status=PaymentStatus.SUCCEEDED,
        payment_method="cod",
        paid_at=now,
        payment_metadata={
            "collected_by": str(current_user.id),
            "collected_by_email": current_user.email,
            "collected_at": now.isoformat(),
        },
    )
    session.add(payment)
    
    # Order is now paid
    order.payment_status = "paid"
    session.add(order)
    session.commit()
    session.refresh(order)
    
    print(f"✅ COD collected for order {order.order_number} by {current_user.email}")
    
    return {
        "message": "COD payment collected successfully",
        "order_id": str(order.id),
        "order_number": order.order_number,
        "amount_collected": float(order.grand_total),
        "payment_status": order.payment_status,
        "collected_by": current_user.email,
    }