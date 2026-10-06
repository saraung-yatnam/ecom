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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlmodel import Session

from app.api.deps import SessionDep, require_perm
from app.core.region import currency_code
from app.models.user import User
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.repositories import order as order_repo
from app.repositories import audit as audit_repo

router = APIRouter(prefix="/admin/cod", tags=["Admin COD"])


@router.get("/pending")
def get_pending_cod_orders(
    session: SessionDep,
    current_user: User = Depends(require_perm("orders.update")),
):
    """
    List all COD orders waiting for cash collection.
    """
    statement = (
        select(Order)
        .where(Order.payment_method == "cod")
        .where(Order.payment_status == "cod_pending")
        .where(Order.status.notin_([OrderStatus.CANCELLED, OrderStatus.REFUNDED, OrderStatus.RTO]))
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
                    "id": str(o.customer_details.id),
                    "full_name": o.customer_details.full_name,
                    "email": o.customer_details.email,
                    "phone": o.customer_details.phone,
                } if o.customer_details else None,
                "grand_total": float(o.grand_total),
                "cod_fee": float(o.cod_fee or 0),
                "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                "payment_status": o.payment_status,
                "collectible": o.status == OrderStatus.DELIVERED,
                "placed_at": o.placed_at.isoformat() if o.placed_at else None,
            }
            for o in orders
        ],
    }


@router.post("/orders/{order_id}/collect", status_code=status.HTTP_200_OK)
def collect_cod_payment(
    order_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_perm("orders.update")),
    request: Request = None,
):
    """
    Mark a COD order's cash as COLLECTED ON DELIVERY.

    - Creates a COD payment record (status=succeeded)
    - Flips the order to payment_status="paid"
    """
    order = order_repo.get_order_by_id(session, order_id, for_update=True)
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
    
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(status_code=400, detail="COD can only be collected for a delivered order")
    existing = session.execute(select(Payment).where(
        Payment.order_id == order.id, Payment.provider == PaymentProvider.COD,
        Payment.status == PaymentStatus.SUCCEEDED,
    )).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="COD payment already recorded; reconcile order state")
    
    # Record the cash collection as a real payment (audit trail + analytics)
    now = datetime.now(timezone.utc)
    payment = Payment(
        order_id=order.id,
        provider=PaymentProvider.COD,
        provider_payment_id=f"cod_{order.order_number}",
        amount=order.grand_total,
        currency=currency_code(),
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
    audit_repo.log_and_commit(session, "cod.collected", "order", order.id, current_user.id,
                              before={"payment_status": "cod_pending"},
                              after={"payment_status": "paid", "amount": str(order.grand_total),
                                     "payment_id": str(payment.id)}, ip_address=audit_repo.client_ip(request))
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
