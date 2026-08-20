import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, get_current_user
from app.models.user import User
from app.repositories import order as order_repo
from app.repositories import payment as payment_repo
from app.schemas.payment import (
    PaymentCreateRequest,
    PaymentRead,
    PaymentIntentResponse,
    PaymentConfirmRequest,
)
from app.services.payment_service import get_payment_service


router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/create-intent", response_model=PaymentIntentResponse)
def create_payment_intent(
    request: PaymentCreateRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """
    Create payment intent.
    
    - Dummy mode: Always succeeds (for testing)
    - Real mode: Creates actual payment intent
    """
    # Get order
    order = order_repo.get_order_by_id(session, request.order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    
    if order.user_id != current_user.id:
        raise HTTPException(403, "Not authorized")
    
    # Get payment service (dummy or real)
    payment_service = get_payment_service()
    
    # Create payment intent
    result = payment_service.create_payment_intent(order, request.payment_method)
    
    # Save payment record
    payment = payment_repo.create_payment(
        session=session,
        order_id=order.id,
        provider="dummy" if result.get("is_dummy", False) else "razorpay",
        provider_payment_id=result["payment_intent_id"],
        amount=result["amount"],
    )
    
    return PaymentIntentResponse(
        client_secret=result["client_secret"],
        payment_intent_id=result["payment_intent_id"],
        order_id=result["order_id"],
        amount=result["amount"],
        currency=result["currency"],
        is_dummy=result.get("is_dummy", True),
    )


@router.post("/confirm", response_model=PaymentRead)
def confirm_payment(
    request: PaymentConfirmRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """
    Confirm payment.
    
    - Dummy mode: Auto-succeeds
    - Real mode: Calls payment provider
    """
    # Get payment
    payment = payment_repo.get_payment_by_provider_id(
        session, request.payment_intent_id
    )
    if not payment:
        raise HTTPException(404, "Payment not found")
    
    # Check order ownership
    order = order_repo.get_order_by_id(session, payment.order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    
    if order.user_id != current_user.id:
        raise HTTPException(403, "Not authorized")
    
    # Get payment service
    payment_service = get_payment_service()
    
    # Confirm payment
    result = payment_service.confirm_payment(request.payment_intent_id)
    
    if result["status"] == "succeeded":
        # Update payment status
        payment = payment_repo.mark_payment_succeeded(
            session, request.payment_intent_id
        )
        # Update order status
        order.status = "confirmed"
        order.payment_status = "paid"
        session.add(order)
        session.commit()
        session.refresh(order)
        
        return payment
    else:
        payment_repo.mark_payment_failed(session, request.payment_intent_id)
        raise HTTPException(400, "Payment failed")