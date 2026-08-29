import json
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
    Payment webhook — configure this URL in the Razorpay dashboard.

    - URL:      https://<your-domain>/api/v1/webhooks/payment
    - Secret:   must match RAZORPAY_WEBHOOK_SECRET in .env
    - Security: Razorpay signs the RAW body (HMAC-SHA256) in the
                X-Razorpay-Signature header; verified before any state change.
                Invalid/missing signatures are rejected with 400.
    - Events handled: payment.captured, order.paid   (payment + order -> paid)
                      refund.processed, refund.failed   (refund state transitions)
    - All other events are acknowledged with 200 and ignored.
    """
    raw_body = (await request.body()).decode("utf-8", errors="replace")
    signature = request.headers.get("x-razorpay-signature", "")

    payment_service = get_payment_service()

    try:
        event = payment_service.handle_webhook(raw_body, signature)
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {str(e)}")

    event_type = event.get("event_type", "unknown")

    # Bad signature / unparseable body -> 400 so Razorpay retries with a valid one
    if event_type in ("invalid_signature", "invalid"):
        raise HTTPException(400, "Invalid webhook signature")

    # ---------------- Dummy mode (local testing, PAYMENT_PROVIDER=dummy) ----------------
    if event.get("is_dummy"):
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            body = {}
        pid = body.get("payment_intent_id") or body.get("razorpay_order_id")
        if event_type == "payment.succeeded" and pid:
            payment = payment_repo.get_payment_by_provider_id(session, pid)
            if payment and payment.status != "succeeded":
                _settle_payment(session, payment, None, None)
        elif event_type in ("refund.processed", "refund.failed"):
            # Dummy/test webhook: body carries the refund entity directly
            _handle_refund_webhook(session, event_type, body.get("refund") or body)
        return {"status": "received", "mode": "dummy", "event_type": event_type}

    # ---------------- Razorpay mode ----------------
    payload = event.get("data") or {}

    if event_type == "payment.captured":
        entity = (payload.get("payment") or {}).get("entity") or {}
        rzp_order_id = entity.get("order_id")   # == our stored provider_payment_id
        if rzp_order_id:
            payment = payment_repo.get_payment_by_provider_id(session, rzp_order_id)
            if payment and payment.status != "succeeded":
                _settle_payment(session, payment, entity.get("method"), entity.get("id"))

    elif event_type == "order.paid":
        entity = (payload.get("order") or {}).get("entity") or {}
        pay_entity = (payload.get("payment") or {}).get("entity") or {}
        if entity.get("id"):
            payment = payment_repo.get_payment_by_provider_id(session, entity["id"])
            if payment and payment.status != "succeeded":
                _settle_payment(session, payment, pay_entity.get("method"), pay_entity.get("id"))

    elif event_type in ("refund.processed", "refund.failed"):
        # Refund events: payload.refund.entity contains the rfnd_xxx with its status
        _handle_refund_webhook(session, event_type, (payload.get("refund") or {}).get("entity") or {})

    # Any other event (payment.failed, refund.created, ...) — acknowledged, no action
    return {"status": "received", "event_type": event_type}