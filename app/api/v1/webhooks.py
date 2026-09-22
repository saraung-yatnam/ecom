from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from sqlmodel import Session

from app.api.deps import SessionDep
from app.models.order import OrderStatus
from app.core.config import settings
from app.services.email_service import email_service
from app.repositories import order as order_repo
from app.repositories import payment as payment_repo
from app.services.payment_service import get_payment_service
from app.services.refund_service import process_refund
from app.services.order_expiry import cancel_pending_online_order, notify_order_cancelled


router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _handle_refund_webhook( 
    session: Session,
    event_type: str,
    refund_entity: dict,
) -> None:
    """
    Handle Razorpay refund webhook events.

    - refund.processed -> payment_status = "refund_completed"
    - refund.failed    -> payment_status = "refund_failed"

    Finds the order by the refund ID stored on it during process_refund().
    """
    refund_id = (refund_entity or {}).get("id")
    if not refund_id:
        print(f"⚠️ {event_type} webhook received without a refund id — ignored")
        return

    order = order_repo.get_order_by_refund_id(session, refund_id)
    if not order:
        print(f"⚠️ {event_type} webhook: no order found for refund_id {refund_id}")
        return

    if event_type == "refund.processed":
        # Only flip to completed if we're still waiting on it — never downgrade
        if order.payment_status != "refund_completed":
            order.payment_status = "refund_completed"
            # The order itself must be REFUNDED (guards + admin stats depend on it).
            # process_refund() sets this at initiation; this is a safety net for
            # orders created before that change / partial-refund edge cases.
            if order.status != OrderStatus.REFUNDED:
                print(f"ℹ️ Order {order.order_number} status was '{order.status.value}' — promoting to REFUNDED")
                order.status = OrderStatus.REFUNDED
            if not order.refunded_at:
                order.refunded_at = datetime.now(timezone.utc)
            session.add(order)

            # Keep the payment record timestamp in sync
            for payment in order.payments or []:
                if not payment.refunded_at:
                    payment.refunded_at = order.refunded_at
                    session.add(payment)

            session.commit()
            session.refresh(order)
            print(f"✅ Refund COMPLETED for order {order.order_number} (webhook: refund.processed)")

            # Email the customer that the money has arrived (non-fatal)
            if settings.SENDGRID_API_KEY and order.user:
                try:
                    email_service.send_refund_completed(order, order.user)
                    print(f"Refund-completed email sent to {order.user.email}")
                except Exception as e:
                    print(f"Failed to send refund-completed email: {str(e)}")
        else:
            print(f"Order {order.order_number} already marked refund_completed — ignoring duplicate event")

    elif event_type == "refund.failed":
        order.payment_status = "refund_failed"
        session.add(order)
        session.commit()
        session.refresh(order)
        print(f"❌ REFUND FAILED for order {order.order_number} (refund_id {refund_id}) — manual intervention needed")

        # Alert the customer (non-fatal)
        if settings.SENDGRID_API_KEY and order.user:
            try:
                email_service.send_refund_failed(order, order.user)
                print(f"Refund-failed email sent to {order.user.email}")
            except Exception as e:
                print(f"Failed to send refund-failed email: {str(e)}")

        # TODO: alert admin (email / Slack / dashboard notification) here


def _settle_payment(session: Session, payment, instrument: str | None, provider_payment_id: str | None):
    """Mark a payment succeeded and flip its order to paid."""
    payment = payment_repo.update_payment_status(
        session,
        payment,
        "succeeded",
        provider_payment_intent=provider_payment_id,
        payment_method=instrument,  # real instrument: upi | card | netbanking | wallet | ...
    )

    order = order_repo.get_order_by_id(session, payment.order_id)
    if order:
        # A payment arriving for an already-CANCELLED order (e.g. the customer
        # paid right as the expiry sweep cancelled it) must be refunded
        # automatically — never hold money for a cancelled order.
        if order.status == OrderStatus.CANCELLED:
            try:
                process_refund(
                    session,
                    order,
                    OrderStatus.PENDING,  # 0% restocking fee
                    reason="Paid after the order was cancelled",
                )
                print(f"♻️ Auto-refunded cancelled order {order.order_number}")
            except Exception as e:
                session.rollback()
                print(f"⚠️ Auto-refund failed for cancelled order {order.order_number}: {e}")
            return payment

        if order.status == OrderStatus.PENDING:
            order.status = OrderStatus.CONFIRMED
        order.payment_status = "paid"
        session.add(order)
        session.commit()
        session.refresh(order)

        # Payment-received confirmation email (non-fatal) — covers users who
        # paid successfully but closed the browser before /payments/confirm
        if settings.SENDGRID_API_KEY and order.user:
            try:
                email_service.send_order_confirmation(order, order.user)
                print(f"Payment confirmation email sent to {order.user.email}")
            except Exception as e:
                print(f"Failed to send payment confirmation email: {str(e)}")
    return payment


@router.post("/payment")
async def payment_webhook(
    request: Request,
    session: SessionDep,
):
    """
    Payment webhook — works for any provider configured via PAYMENT_PROVIDER.

    - URL:      https://<your-domain>/api/v1/webhooks/payment
    - Security: each provider signs the RAW body with its own signature and
                header; verification happens inside the provider service
                (Stripe-Signature for Stripe, X-Razorpay-Signature for
                Razorpay). Invalid/missing signatures are rejected with 400.
    - Events handled (normalized):
                  payment.succeeded   -> payment + order paid
                  refund.processed    -> refund state transition
                  refund.failed       -> refund state transition
    - All other events are acknowledged with 200 and ignored.
    """
    raw_body = (await request.body()).decode("utf-8", errors="replace")
    signature = request.headers.get("stripe-signature") or request.headers.get("x-razorpay-signature", "")

    payment_service = get_payment_service()

    try:
        event = payment_service.handle_webhook(raw_body, signature)
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {str(e)}")

    event_type = event.get("event_type", "unknown")

    # Bad signature / unparseable body -> 400 so the provider retries with a valid one
    if event_type in ("invalid_signature", "invalid"):
        raise HTTPException(400, "Invalid webhook signature")

    # ---------------- Payment succeeded ----------------
    if event_type == "payment.succeeded":
        payment_id = event.get("payment_id") or (event.get("data") or {}).get("payment_intent_id")
        if payment_id:
            payment = payment_repo.get_payment_by_provider_id(session, payment_id)
            if payment and payment.status != "succeeded":
                _settle_payment(
                    session,
                    payment,
                    event.get("payment_method"),
                    event.get("transaction_id"),
                )

    elif event_type in ("refund.processed", "refund.failed"):
        refund_id = event.get("refund_id")
        if refund_id:
            _handle_refund_webhook(session, event_type, {"id": refund_id})

    # ---------------- Payment abandoned / failed (webhook reconciliation) ----
    elif event_type in ("payment.cancelled", "payment.failed"):
        payment_id = event.get("payment_id") or (event.get("data") or {}).get("payment_intent_id")
        if payment_id:
            payment = payment_repo.get_payment_by_provider_id(session, payment_id)
            if payment:
                order = order_repo.get_order_by_id(session, payment.order_id)
                if order:
                    cancelled = cancel_pending_online_order(
                        session,
                        order,
                        reason="Payment was cancelled or failed before it completed — order cancelled.",
                    )
                    if cancelled:
                        notify_order_cancelled(session, order)
                        print(f"🗑️ Order {order.order_number} cancelled (webhook {event_type})")

    # Any other event — acknowledged, no action
    return {"status": "received", "event_type": event_type}