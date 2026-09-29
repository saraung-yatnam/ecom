# app/services/refund_service.py
"""Refund business logic: fee calculation, stock restoration, Razorpay refunds."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core.config import settings
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus
from app.models.product import ProductVariant
from app.models.refund import Refund, RefundStatus
from app.models.user import User
from app.repositories import payment as payment_repo
from app.repositories import rbac as rbac_repo
from app.repositories import refund as refund_repo
from app.services.payment_service import get_payment_service, get_payment_service_for_payment


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


def _resolve_razorpay_payment_id(payment: Payment, service=None) -> str:
    """
    Resolve the actual charge/payment ID (pay_xxx / ch_xxx) needed for refunds.

    - provider_payment_intent holds pay_xxx/ch_xxx once the webhook settled it
    - otherwise fetch it from the payment's OWN provider via
      get_payment_id_for_order(order_xxx) — never the globally configured one
    - dummy mode: fall back to whatever is stored

    ``service`` may be passed in (already per-payment routed) to avoid building
    it twice; when omitted it is routed from ``payment.provider``.
    """
    if payment.provider_payment_intent:
        return payment.provider_payment_intent

    if service is None:
        try:
            service = get_payment_service_for_payment(payment)
        except ValueError:
            return payment.provider_payment_id
    resolver = getattr(service, "get_payment_id_for_order", None)
    if callable(resolver):
        try:
            resolved = resolver(payment.provider_payment_id)
        except Exception:
            resolved = None
        if resolved:
            return resolved

    # Dummy mode / last resort
    return payment.provider_payment_id


def process_refund(
    session: Session,
    order: Order,
    status_at_cancellation: OrderStatus,
    reason: str | None = None,
    requested_by: UUID | None = None,
    approved_by: UUID | None = None,
    idempotency_key: str | None = None,
    amount: Decimal | None = None,
) -> dict:
    """
    Execute a refund for an order via the configured provider.

    Every execution is recorded in the ``refunds`` ledger keyed by
    ``idempotency_key`` (default ``refund-<order>-<status>``):

    - same key + EXECUTED row  -> replayed result, NO second PSP call;
    - same key + PENDING row    -> the pending approval is executed in place;
    - same key + FAILED row     -> a fresh attempt row is created;
    - concurrent duplicate insert -> loser replays the winner's row.

    ``amount`` caps the refund (partial refunds); None refunds the full
    remaining balance. Updates the order's refund fields and marks the
    payment record refunded. Returns a refund info dict for API responses.
    """
    calc = calculate_refund(order, status_at_cancellation)
    remaining = calc["refund_amount"]
    restocking_fee = calc["restocking_fee"]

    refund_amount = remaining if amount is None else min(_money(amount), remaining)

    base = {
        "processed": False,
        "amount": refund_amount,
        "restocking_fee": restocking_fee,
        "fee_percentage": calc["fee_percentage"],
        "refund_id": None,
        "status": None,
        "requires_approval": False,
        "duplicate": False,
    }

    if refund_amount <= 0:
        return {**base, "message": "Nothing to refund (order already fully refunded)"}

    key = idempotency_key or f"refund-{order.id}-{status_at_cancellation.value}"
    now = datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)

    existing = refund_repo.get_by_idempotency_key(session, key)
    if existing is not None and existing.status == RefundStatus.EXECUTED:
        return {
            **base,
            "processed": True,
            "duplicate": True,
            "amount": existing.amount,
            "refund_id": existing.provider_refund_id,
            "status": existing.provider_status,
            "message": "Refund already processed for this request (idempotent replay)",
        }
    if existing is not None and existing.status == RefundStatus.PENDING_APPROVAL:
        ledger = existing
        ledger.amount = refund_amount
        # Keep the fee captured at request time (computed from the
        # pre-cancel status) — approval-time recomputation would zero it.
        restocking_fee = ledger.restocking_fee
        if approved_by is not None:
            ledger.approved_by = approved_by
    elif existing is not None:
        # FAILED / REJECTED rows are history — retry as a fresh attempt.
        key = f"{key}-retry-{existing.created_at.strftime('%Y%m%d%H%M%S')}"
        ledger = Refund(
            order_id=order.id,
            amount=refund_amount,
            restocking_fee=restocking_fee,
            idempotency_key=key,
            status=RefundStatus.EXECUTED,
            reason=reason,
            requested_by=requested_by,
            approved_by=approved_by,
        )
        session.add(ledger)
    else:
        ledger = Refund(
            order_id=order.id,
            amount=refund_amount,
            restocking_fee=restocking_fee,
            idempotency_key=key,
            status=RefundStatus.EXECUTED,
            reason=reason,
            requested_by=requested_by,
            approved_by=approved_by,
        )
        session.add(ledger)

    try:
        # Savepoint (not a full rollback): the caller may already have staged
        # changes (e.g. order.status=CANCELLED) that must survive a lost
        # duplicate-key race.
        savepoint = session.begin_nested()
        session.flush()
    except IntegrityError:
        savepoint.rollback()
        winner = refund_repo.get_by_idempotency_key(session, key)
        if winner is not None and winner.status == RefundStatus.EXECUTED:
            return {
                **base,
                "processed": True,
                "duplicate": True,
                "amount": winner.amount,
                "refund_id": winner.provider_refund_id,
                "status": winner.provider_status,
                "message": "Refund already processed for this request (idempotent replay)",
            }
        raise

    payment = _get_refundable_payment(session, order)
    if not payment:
        ledger.status = RefundStatus.FAILED
        ledger.error = "No successful payment found for this order"
        session.add(ledger)
        session.commit()
        return {**base, "message": "No successful payment found for this order"}

    # Route to the gateway that captured THIS payment — not the global
    # setting (a Razorpay order_xxx sent to Stripe is the "No such
    # payment_intent" failure). COD has no online money: refuse with a
    # clear message instead of calling any PSP.
    try:
        service = get_payment_service_for_payment(payment)
    except ValueError as e:
        ledger.status = RefundStatus.FAILED
        ledger.error = str(e)
        session.add(ledger)
        session.commit()
        return {**base, "message": str(e)}

    razorpay_payment_id = _resolve_razorpay_payment_id(payment, service)

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

        ledger.status = RefundStatus.EXECUTED
        ledger.provider_refund_id = result["refund_id"]
        ledger.provider_status = result.get("status")
        ledger.decided_at = now
        session.add(ledger)

        session.commit()
        session.refresh(order)

        return {
            **base,
            "processed": True,
            "refund_id": result["refund_id"],
            "status": result.get("status"),
            "payment_status": order.payment_status,
            "refund_row_id": str(ledger.id),
            "message": (
                f"Refund of ₹{refund_amount} initiated successfully. "
                f"It will reflect in your account within "
                f"{settings.REFUND_PROCESSING_DAYS} business days."
            ),
        }

    ledger.status = RefundStatus.FAILED
    ledger.provider_status = result.get("status")
    ledger.error = result.get("error", "unknown error")
    session.add(ledger)
    session.commit()

    # Provider/ledger mismatch probe (failure path only — no happy-path
    # cost): money refunded OUTSIDE the app (e.g. gateway dashboard) leaves
    # our ledger stale, and every retry then fails the same way. If the
    # provider reports MORE refunded than we recorded, attach ground truth
    # so callers can offer reconciliation instead of another doomed retry.
    provider_state = _detect_provider_mismatch(
        service, razorpay_payment_id, order
    )
    if provider_state is not None:
        return {
            **base,
            "status": result.get("status"),
            "provider_state": provider_state,
            "message": (
                f"Our records show ₹{order.refund_amount or 0} refunded, but "
                f"{provider_state['provider']} reports "
                f"₹{provider_state['provider_refunded']} already refunded "
                f"(₹{provider_state['provider_remaining']} left on the charge). "
                "Sync records to reconcile, then refund the remainder."
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


def _detect_provider_mismatch(service, provider_payment_id: str, order: Order) -> dict | None:
    """Compare provider-side refunded total against our ledger.

    Returns ground truth when the provider shows MORE refunded than we
    recorded (external refund), else None. Test doubles without the query
    method (getattr guard) simply skip the probe.
    """
    query = getattr(service, "get_charge_refund_state", None)
    if not callable(query):
        return None
    try:
        state = query(provider_payment_id)
    except Exception:
        return None
    if not state:
        return None
    try:
        provider_refunded = Decimal(str(state.get("refunded_total") or 0))
    except Exception:
        return None
    recorded = order.refund_amount or Decimal(0)
    if provider_refunded <= recorded:
        return None
    provider_name = (
        "Stripe" if str(provider_payment_id).startswith(("pi_", "ch_")) else "Razorpay"
    )
    remaining = Decimal(str(state.get("charge_total") or 0)) - provider_refunded
    return {
        "provider": provider_name,
        "provider_refunded": float(provider_refunded),
        "provider_remaining": float(max(remaining, Decimal(0))),
        "recorded_refunded": float(recorded),
        "refunds": state.get("refunds") or [],
    }


def fetch_refund_status(order: Order, session=None) -> dict:
    """Fetch live refund status from the payment provider.

    Routes via the order's own payment row when a session is available;
    falls back to the global provider for legacy callers (status endpoint
    without a payment lookup).
    """
    if session is not None:
        try:
            payment = _get_refundable_payment(session, order)
            if payment is not None:
                return get_payment_service_for_payment(payment).get_refund_status(
                    order.refund_id
                )
        except ValueError:
            return {"status": "failed", "refund_id": order.refund_id,
                    "error": "Cash on Delivery orders have no online refund"}
        except Exception:
            pass
    service = get_payment_service()
    return service.get_refund_status(order.refund_id)


def effective_refund_limit(session: Session, user: User) -> Decimal | None:
    """Highest single-refund amount the user may execute WITHOUT approval.

    None = unlimited (any role with a NULL limit, e.g. admin).
    """
    roles = rbac_repo.get_user_roles(session, user.id)
    limits = [r.max_refund_amount for r in roles if r.max_refund_amount is not None]
    if len(limits) < len(roles):
        return None
    return max(limits) if limits else Decimal(0)


def status_at_cancellation(session: Session, order: Order) -> OrderStatus:
    """Best-effort recovery of the status an order held when it was cancelled.

    The restocking fee is keyed on the status AT cancellation time, but a
    follow-up refund necessarily runs when ``order.status`` is already
    ``cancelled`` — which is not in ``RESTOCKING_FEE_MAP`` and would silently
    refund 100% of the total. The ``order.cancelled`` audit entry records the
    prior status, so read it back from there.

    Falls back to CONFIRMED (the 5% mid-tier) when no audit entry exists,
    which is the conservative choice: it never over-refunds a customer.
    """
    from sqlalchemy import select

    from app.models.admin_audit import AdminAuditLog

    row = session.execute(
        select(AdminAuditLog.before)
        .where(
            AdminAuditLog.entity == "order",
            AdminAuditLog.entity_id == str(order.id),
            AdminAuditLog.action == "order.cancelled",
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if isinstance(row, dict):
        raw = row.get("status")
        try:
            recovered = OrderStatus(raw)
        except ValueError:
            recovered = None
        # Only cancellable states are ever recorded as the prior status, so
        # this is guaranteed to have a fee attached.
        if recovered in RESTOCKING_FEE_MAP:
            return recovered

    return OrderStatus.CONFIRMED


def refund_authorization(
    session: Session, user: User, order: Order, amount: Decimal
) -> dict:
    """Decide whether an admin refund executes or needs a second admin.

    Requires approval when:
    - the order was placed by staff and the requester owns it (self-dealing);
    - the amount exceeds the requester's effective role limit.
    """
    if order.user_id == user.id and getattr(order, "placed_by_staff", False):
        return {
            "requires_approval": True,
            "reason": "Order was placed by you — a different admin must approve",
        }
    limit = effective_refund_limit(session, user)
    if limit is not None and amount > limit:
        return {
            "requires_approval": True,
            "reason": (
                f"₹{amount} exceeds your single-refund limit of ₹{limit} — "
                "a different admin must approve"
            ),
        }
    return {"requires_approval": False, "reason": None}


def request_admin_refund(
    session: Session,
    order: Order,
    requested_by: User,
    reason: str,
    amount: Decimal | None = None,
    idempotency_key: str | None = None,
    status_at: OrderStatus | None = None,
) -> dict:
    """Admin refund entry point: execute within authority, else stage approval.

    Always returns a dict with ``requires_approval``. Approval rows are
    executed later via :func:`approve_refund` by a different admin.
    """
    basis = status_at or order.status
    calc = calculate_refund(order, basis)
    target = calc["refund_amount"] if amount is None else min(_money(amount), calc["refund_amount"])
    if target <= 0:
        return {
            "processed": False,
            "requires_approval": False,
            "amount": target,
            "message": "Nothing to refund (order already fully refunded)",
        }

    gate = refund_authorization(session, requested_by, order, target)
    key = idempotency_key or f"refund-{order.id}-{basis.value}"

    if not gate["requires_approval"]:
        return process_refund(
            session,
            order,
            basis,
            reason=reason,
            requested_by=requested_by.id,
            approved_by=requested_by.id,
            idempotency_key=key,
            amount=target,
        )

    # Stage for second-admin approval — NO PSP call here.
    existing = refund_repo.get_by_idempotency_key(session, key)
    if existing is not None and existing.status == RefundStatus.PENDING_APPROVAL:
        ledger = existing
    elif existing is not None and existing.status == RefundStatus.EXECUTED:
        return {
            "processed": True,
            "requires_approval": False,
            "duplicate": True,
            "amount": existing.amount,
            "refund_id": existing.provider_refund_id,
            "message": "Refund already processed for this request (idempotent replay)",
        }
    else:
        if existing is not None:
            key = f"{key}-{_ledger_suffix()}"
        ledger = Refund(
            order_id=order.id,
            amount=target,
            restocking_fee=calc["restocking_fee"],
            idempotency_key=key,
            status=RefundStatus.PENDING_APPROVAL,
            reason=reason,
            requested_by=requested_by.id,
        )
        session.add(ledger)
        session.commit()
        session.refresh(ledger)
    return {
        "processed": False,
        "requires_approval": True,
        "amount": target,
        "refund_row_id": str(ledger.id),
        "message": gate["reason"],
    }


def _ledger_suffix() -> str:
    """Short unique suffix for retry/duplicate ledger keys."""
    from uuid import uuid4

    return uuid4().hex[:8]


def approve_refund(
    session: Session, ledger: Refund, approver: User
) -> dict:
    """Execute a pending approval. Guards (all enforced here, not just at
    the route, so no caller can skip them):
    - approver differs from requester AND order owner (four-eyes rule);
    - approver is themselves authorized for the amount — otherwise an
      under-limit manager could rubber-stamp any pending refund and the
      per-role limits would be theater.
    """
    order = session.get(Order, ledger.order_id)
    if order is None:
        raise ValueError("Order for this refund no longer exists")
    if ledger.status != RefundStatus.PENDING_APPROVAL:
        raise ValueError(f"Refund is {ledger.status.value}, not pending approval")
    if approver.id == ledger.requested_by:
        raise ValueError("The requesting admin cannot approve their own refund")
    if approver.id == order.user_id:
        raise ValueError("The order owner cannot approve this refund")
    limit = effective_refund_limit(session, approver)
    if limit is not None and ledger.amount > limit:
        raise ValueError(
            f"This refund (₹{ledger.amount}) exceeds your approval authority "
            f"of ₹{limit} — an admin must approve it"
        )

    return process_refund(
        session,
        order,
        order.status,
        reason=ledger.reason,
        requested_by=ledger.requested_by,
        approved_by=approver.id,
        idempotency_key=ledger.idempotency_key,
        amount=ledger.amount,
    )


def reject_refund(
    session: Session, ledger: Refund, approver: User, note: str | None = None
) -> Refund:
    """Reject a pending approval (no money moves)."""
    if ledger.status != RefundStatus.PENDING_APPROVAL:
        raise ValueError(f"Refund is {ledger.status.value}, not pending approval")
    if approver.id == ledger.requested_by:
        raise ValueError("The requesting admin cannot reject their own refund")
    ledger.status = RefundStatus.REJECTED
    ledger.approved_by = approver.id
    ledger.decided_at = datetime.now(timezone.utc)
    if note:
        ledger.error = note
    session.add(ledger)
    session.commit()
    session.refresh(ledger)
    return ledger
