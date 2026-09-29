# app/services/order_expiry.py
"""Abandoned unpaid online orders: auto-cancel + restock.

Flow: an online order is placed with status=PENDING and held stock but the
customer never pays. The APScheduler sweep (see main.py) runs
``expire_stale_pending_orders()`` on an interval; whenever a PENDING online
order is older than ``PENDING_ORDER_EXPIRY_MINUTES`` it:

  * cancels any still-pending provider PaymentIntent (best-effort),
  * restores the held stock,
  * marks the order cancelled (payment_status=cancelled),
  * emails the customer and notifies admins.

The same ``cancel_pending_online_order()`` helper is reused by the webhook
reconciliation path (Stripe payment_intent.canceled / Razorpay payment.failed).
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlmodel import Session

from app.core.config import settings
from app.models.order import Order, OrderStatus
from app.models.payment import PaymentStatus
from app.models.user import User
from app.repositories import payment as payment_repo
from app.repositories import notification as notification_repo
from app.services.email_service import email_service
from app.services.payment_service import (
    get_payment_service_for_payment,
)
from app.services.refund_service import restore_stock


def cancel_pending_online_order(
    session: Session,
    order: Order,
    reason: str = "Payment not completed — order cancelled.",
) -> bool:
    """Cancel a still-unpaid PENDING online order and release its stock.

    Returns True if the order was cancelled, False if it was not in a
    cancellable state (idempotent — safe for webhook retries and races).
    """
    if order.status != OrderStatus.PENDING:
        return False

    now = datetime.now(timezone.utc)

    # Best-effort: cancel the provider PaymentIntent(s) so money is never
    # captured for an order we are giving up on.
    payments = payment_repo.get_payments_by_order(session, order.id)
    for payment in payments or []:
        if payment.status == PaymentStatus.PENDING:
            try:
                get_payment_service_for_payment(
                    payment
                ).cancel_payment_intent(payment.provider_payment_id)
            except Exception as e:
                print(f"⚠️ Could not cancel provider intent {payment.provider_payment_id}: {e}")

    order.status = OrderStatus.CANCELLED
    order.payment_status = "cancelled"
    order.cancellation_reason = reason
    order.cancelled_at = now
    session.add(order)

    restore_stock(session, order)

    session.commit()
    session.refresh(order)
    return True


def notify_order_cancelled(session: Session, order: Order) -> None:
    """Email the customer and notify admins about a cancelled order (non-fatal)."""
    try:
        user = session.get(User, order.user_id)
        if settings.SENDGRID_API_KEY and user:
            email_service.send_order_cancelled(order, user)
    except Exception as e:
        print(f"⚠️ Failed to send cancellation email for {order.order_number}: {e}")

    try:
        notification_repo.notify_admins_order_cancelled(session, order)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"⚠️ Failed to create cancellation notifications for {order.order_number}: {e}")


def expire_stale_pending_orders(session: Session) -> dict:
    """Auto-cancel every unpaid online order older than the expiry window."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.PENDING_ORDER_EXPIRY_MINUTES
    )
    statement = (
        select(Order)
        .where(
            Order.payment_method == "online",
            Order.status == OrderStatus.PENDING,
            Order.payment_status == "pending",
            Order.placed_at < cutoff,
        )
        .order_by(Order.placed_at.asc())
        .options(selectinload(Order.items), selectinload(Order.user))
    )
    orders = session.execute(statement).scalars().all()

    cancelled: list[str] = []
    for order in orders:
        try:
            ok = cancel_pending_online_order(
                session,
                order,
                "Payment window expired — order auto-cancelled.",
            )
            if ok:
                cancelled.append(order.order_number)
                notify_order_cancelled(session, order)
        except Exception as e:
            session.rollback()
            print(f"⚠️ Failed to auto-expire order {order.order_number}: {e}")

    return {"cancelled": len(cancelled), "order_numbers": cancelled}