# app/services/refund_service.py
"""Refund business logic: fee calculation, stock restoration, Razorpay refunds."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlmodel import Session

from app.core.config import settings
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus
from app.models.product import ProductVariant
from app.repositories import payment as payment_repo
from app.services.payment_service import get_payment_service


# Restocking fee % keyed by the order status AT THE TIME of cancellation
RESTOCKING_FEE_MAP = {
    OrderStatus.PENDING: lambda: settings.RESTOCKING_FEE_PENDING,        # 0%
    OrderStatus.CONFIRMED: lambda: settings.RESTOCKING_FEE_CONFIRMED,    # 5%
    OrderStatus.PROCESSING: lambda: settings.RESTOCKING_FEE_PROCESSING,  # 15%
}

# Provider refund-status values that mean "refund was accepted and is in flight"
# (Razorpay: processed/pending · Stripe: succeeded/processing/requires_action · dummy: processed)
REFUND_ACCEPTED_STATUSES = {
    "processed",
    "pending",
    "succeeded",
    "processing",
    "requires_action",
}

# Provider refund-status values that mean the money has arrived back
REFUND_COMPLETED_STATUSES = {"processed", "succeeded"}


def _money(value: Decimal) -> Decimal:
    """Round to 2 decimal places (currency)."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_refund(order: Order, status_at_cancellation: OrderStatus) -> dict:
    """
    Calculate the refund amount and restocking fee for an order.

    refund_amount = grand_total - restocking_fee - already_refunded
    """
    fee_getter = RESTOCKING_FEE_MAP.get(status_at_cancellation)
    fee_percentage = fee_getter() if fee_getter else 0.0

    restocking_fee = _money(Decimal(str(fee_percentage)) / 100 * order.grand_total)
    already_refunded = order.refund_amount or Decimal(0)

    refund_amount = order.grand_total - restocking_fee - already_refunded
    refund_amount = max(_money(refund_amount), Decimal(0))

    return {
        "refund_amount": refund_amount,
        "restocking_fee": restocking_fee,
        "fee_percentage": fee_percentage,
        "already_refunded": already_refunded,
    }


def restore_stock(session: Session, order: Order) -> int:
    """
    Restore product stock for every item in the order.
    Returns the number of variants updated.
    """
    restored = 0
    for item in order.items or []:
        variant = session.get(ProductVariant, item.variant_id)
        if variant:
            variant.stock += item.quantity
            session.add(variant)
            restored += 1
            print(f"📦 Restored stock: {variant.sku} +{item.quantity} (now {variant.stock})")
    return restored


def _get_refundable_payment(session: Session, order: Order) -> Payment | None:
    """Find the succeeded payment record for an order (if any)."""
    payments = payment_repo.get_payments_by_order(session, order.id)
    for payment in payments:
        if payment.status == PaymentStatus.SUCCEEDED:
            return payment
    return None


def _resolve_razorpay_payment_id(payment: Payment) -> str:
    """
    Resolve the actual Razorpay payment ID (pay_xxx) needed for refunds.

    - provider_payment_intent holds pay_xxx once the webhook settled it
    - otherwise fetch it from Razorpay via the order ID (order_xxx)
    - dummy mode: fall back to whatever is stored
    """
    if payment.provider_payment_intent:
        return payment.provider_payment_intent

    service = get_payment_service()
    resolver = getattr(service, "get_payment_id_for_order", None)
    if callable(resolver):
        resolved = resolver(payment.provider_payment_id)
        if resolved:
            return resolved

    # Dummy mode / last resort
    return payment.provider_payment_id


def process_refund(
    session: Session,
    order: Order,
    status_at_cancellation: OrderStatus,
    reason: str | None = None,
) -> dict:
    """
    Process a refund for a paid online order via the configured provider.

    Updates the order's refund fields and marks the payment record refunded.
    Returns a refund info dict suitable for the API response.
    """
    calc = calculate_refund(order, status_at_cancellation)
    refund_amount = calc["refund_amount"]
    restocking_fee = calc["restocking_fee"]

    base = {
        "processed": False,
        "amount": refund_amount,
        "restocking_fee": restocking_fee,
        "fee_percentage": calc["fee_percentage"],
        "refund_id": None,
        "status": None,
    }

    if refund_amount <= 0:
        return {**base, "message": "Nothing to refund (order already fully refunded)"}

    payment = _get_refundable_payment(session, order)
    if not payment:
        return {**base, "message": "No successful payment found for this order"}

    razorpay_payment_id = _resolve_razorpay_payment_id(payment)

    service = get_payment_service()
    result = service.create_refund(
        razorpay_payment_id,
        amount=float(refund_amount),
        notes={
            "order_id": str(order.id),
            "order_number": order.order_number,
            "reason": reason or "Order cancelled",
        },
    )

    if result.get("status") in REFUND_ACCEPTED_STATUSES:
        now = datetime.now(timezone.utc)

        order.refund_amount = (order.refund_amount or Decimal(0)) + refund_amount
        order.refund_id = result["refund_id"]
        order.refund_reason = reason
        order.restocking_fee = restocking_fee
        order.refunded_at = now

        # ------------------------------------------------------------------
        # Order status — once a refund is successfully initiated the order
        # is no longer just "cancelled"; it is REFUNDED. This powers:
        #   * the existing guard `if order.status == REFUNDED: already refunded`
        #   * admin dashboard stats (`refunded_orders` count)
        # ------------------------------------------------------------------
        order.status = OrderStatus.REFUNDED

        # ------------------------------------------------------------------
        # User-facing payment_status — distinct phases instead of ambiguous
        # "refunded":
        #   * refund_initiated  -> submitted to Razorpay, money NOT yet there
        #                          (live mode: 1-5 days, completed later by
        #                          the refund.processed webhook)
        #   * refund_completed  -> provider returned "processed" (test/dummy
        #                          mode & instant methods e.g. UPI) OR the
        #                          webhook confirmed the money reached the bank
        # ------------------------------------------------------------------
        provider_status = result.get("status")
        if provider_status in REFUND_COMPLETED_STATUSES:
            order.payment_status = "refund_completed"
            print(f"✅ Refund COMPLETED for order {order.order_number} (provider returned processed)")
        else:
            order.payment_status = "refund_initiated"
            print(f"⏳ Refund INITIATED for order {order.order_number} — waiting for refund.processed webhook")
        session.add(order)

        payment.status = PaymentStatus.REFUNDED
        payment.refunded_at = now
        session.add(payment)

        session.commit()
        session.refresh(order)

        return {
            **base,
            "processed": True,
            "refund_id": result["refund_id"],
            "status": result.get("status"),
            "payment_status": order.payment_status,
            "message": (
                f"Refund of ₹{refund_amount} initiated successfully. "
                f"It will reflect in your account within "
                f"{settings.REFUND_PROCESSING_DAYS} business days."
            ),
        }

    return {
        **base,
        "status": result.get("status"),
        "message": (
            f"Refund failed: {result.get('error', 'unknown error')}. "
            "The order was cancelled — please contact support for the refund."
        ),
    }


def fetch_refund_status(order: Order) -> dict:
    """Fetch live refund status from the payment provider."""
    service = get_payment_service()
    return service.get_refund_status(order.refund_id)
