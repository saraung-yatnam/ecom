import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, CurrentUser
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
from app.services.email_service import email_service
from app.core.config import settings


router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/create-intent", response_model=PaymentIntentResponse)
def create_payment_intent(
    request: PaymentCreateRequest,
    session: SessionDep,
    current_user: CurrentUser,
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
    
    # 🚫 COD orders are paid in cash on delivery — no online intent
    if order.payment_method == "cod":
        raise HTTPException(
            400,
            "This is a Cash on Delivery order. Payment will be collected on delivery.",
        )
    
    # Get payment service (dummy or real)
    payment_service = get_payment_service()
    
    # Create payment intent
    result = payment_service.create_payment_intent(order, request.payment_method)
    
    # Save payment record
    payment = payment_repo.create_payment(
        session=session,
        order_id=order.id,
        provider="dummy" if result.get("is_dummy", False) else settings.PAYMENT_PROVIDER,
        provider_payment_id=result["payment_intent_id"],
        amount=result["amount"],
        currency=result.get("currency") or settings.PAYMENT_CURRENCY,
        payment_method=order.payment_method or request.payment_method,
    )
    
    return PaymentIntentResponse(
        client_secret=result["client_secret"],
        payment_intent_id=result["payment_intent_id"],
        order_id=result["order_id"],
        amount=result["amount"],
        currency=result["currency"],
        provider=result.get("provider") or ("dummy" if result.get("is_dummy", False) else settings.PAYMENT_PROVIDER),
        is_dummy=result.get("is_dummy", True),
    )


@router.post("/confirm", response_model=PaymentRead)
def confirm_payment(
    request: PaymentConfirmRequest,
    session: SessionDep,
    current_user: CurrentUser,
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
    
    # 🚫 COD orders can't be confirmed online — admin collects cash on delivery
    if order.payment_method == "cod":
        raise HTTPException(
            400,
            "Cash on Delivery orders cannot be confirmed online. Payment is collected on delivery.",
        )
    
    # Get payment service
    payment_service = get_payment_service()
    
    # Confirm payment
    result = payment_service.confirm_payment(request.payment_intent_id)
    
    if result["status"] == "succeeded":
        # Resolve the real transaction ID (pay_xxx) — prefer the value passed
        # from the checkout callback, else fetch it from the provider, else
        # fall back to whatever confirm returned (dummy_txn_... in dev).
        transaction_id = request.transaction_id
        if not transaction_id and not result.get("is_dummy", True):
            resolver = getattr(payment_service, "get_payment_id_for_order", None)
            if callable(resolver):
                transaction_id = resolver(payment.provider_payment_id)
        transaction_id = transaction_id or result.get("transaction_id") or payment.provider_payment_id

        # Update payment status (payment_method = real instrument from Razorpay: upi/card/netbanking/...)
        payment = payment_repo.mark_payment_succeeded(
            session, request.payment_intent_id,
            payment_method=result.get("method"),
            provider_payment_intent=transaction_id,
        )
        # Update order status
        order.status = "confirmed"
        order.payment_status = "paid"
        session.add(order)
        session.commit()
        session.refresh(order)
        
        # Send payment-received confirmation email (non-fatal)
        if settings.SENDGRID_API_KEY:
            try:
                user = session.get(User, order.user_id)
                if user:
                    email_service.send_order_confirmation(order, user)
                    print(f"Payment confirmation email sent to {user.email}")
            except Exception as e:
                print(f"Failed to send payment confirmation email: {str(e)}")
        
        return payment
    else:
        payment_repo.mark_payment_failed(session, request.payment_intent_id)
        raise HTTPException(400, "Payment failed")