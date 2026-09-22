from app.services.payment_service import PaymentService
from app.core.config import settings

# Try to import stripe
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    print("⚠️ Stripe not installed. Install with: uv add stripe")


class StripePaymentService(PaymentService):
    """Stripe payment service implementation."""

    @staticmethod
    def _get(obj, key, default=None):
        """Read a field from a Stripe object/dict without knowing its access style."""
        if obj is None:
            return default
        try:
            return obj[key]
        except (KeyError, TypeError, IndexError):
            return getattr(obj, key, default)

    def __init__(self):
        self.secret_key = settings.STRIPE_SECRET_KEY
        self.publishable_key = settings.STRIPE_PUBLISHABLE_KEY
        self.webhook_secret = settings.STRIPE_WEBHOOK_SECRET
        self.currency = (settings.PAYMENT_CURRENCY or "INR").lower()

        print(f"Stripe Available: {STRIPE_AVAILABLE}")
        print(f"Stripe Secret Key: {'***' if self.secret_key else 'None'}")
        print(f"Stripe Webhook Secret: {'***' if self.webhook_secret else 'None'}")

        if not STRIPE_AVAILABLE:
            print("❌ Stripe library not installed. Falling back to dummy.")
            self.is_configured = False
            return

        if not self.secret_key:
            print("❌ Stripe secret key not set. Falling back to dummy.")
            self.is_configured = False
            return

        self.is_configured = True
        try:
            stripe.api_key = self.secret_key
            print(f"✅ Stripe initialized with key: {self.secret_key[:7]}...")
        except Exception as e:
            print(f"❌ Stripe initialization failed: {str(e)}")
            self.is_configured = False

    def _production_raise(self, message):
        if settings.ENVIRONMENT == "production":
            raise RuntimeError(message)
        return None

    def _amount_in_smallest_unit(self, amount) -> int:
        """Stripe minor units: cents for two-decimal currencies."""
        return int(float(amount) * 100)

    def create_payment_intent(self, order, payment_method="card"):
        """Create a Stripe PaymentIntent."""
        if not self.is_configured:
            if settings.ENVIRONMENT == "production":
                raise RuntimeError("Stripe is not configured but ENVIRONMENT=production. No dummy fallback.")
            from app.services.payment_service import DummyPaymentService
            print("⚠️ Using dummy payment (Stripe not configured)")
            return DummyPaymentService().create_payment_intent(order, payment_method)

        try:
            payment_intent = stripe.PaymentIntent.create(
                amount=self._amount_in_smallest_unit(order.grand_total),
                currency=self.currency,
                automatic_payment_methods={"enabled": True},
                metadata={
                    "order_id": str(order.id),
                    "order_number": order.order_number,
                },
            )

            print(f"✅ Stripe PaymentIntent created: {payment_intent['id']}")

            return {
                "client_secret": payment_intent.client_secret,
                "payment_intent_id": payment_intent.id,
                "order_id": str(order.id),
                "amount": float(order.grand_total),
                "currency": payment_intent.currency.upper(),
                "is_dummy": False,
                "payment_intent": payment_intent,
            }
        except Exception as e:
            print(f"❌ Stripe PaymentIntent creation failed: {str(e)}")
            if settings.ENVIRONMENT == "production":
                raise RuntimeError(f"Stripe PaymentIntent creation failed: {str(e)}")
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().create_payment_intent(order, payment_method)

    def confirm_payment(self, payment_intent_id):
        """Fetch Stripe PaymentIntent status."""
        if not self.is_configured:
            if settings.ENVIRONMENT == "production":
                raise RuntimeError("Stripe is not configured but ENVIRONMENT=production. No dummy fallback.")
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().confirm_payment(payment_intent_id)

        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            method = None
            pm_id = self._get(intent, "payment_method")
            if pm_id:
                try:
                    pm = stripe.PaymentMethod.retrieve(pm_id)
                    method = self._get(pm, "type")
                except Exception as pe:
                    print(f"⚠️ Could not read payment method from Stripe: {pe}")
            status = self._get(intent, "status")
            if status == "succeeded":
                return {"status": "succeeded", "payment_intent_id": payment_intent_id, "is_dummy": False, "method": method}
            elif status in ("processing", "requires_action", "requires_confirmation", "requires_capture"):
                return {"status": "pending", "payment_intent_id": payment_intent_id, "is_dummy": False}
            else:
                error = self._get(intent, "last_payment_error") or {}
                return {"status": "failed", "payment_intent_id": payment_intent_id, "is_dummy": False,
                        "error": self._get(error, "message")}
        except Exception as e:
            print(f"❌ Stripe PaymentIntent fetch failed: {str(e)}")
            return {"status": "failed", "payment_intent_id": payment_intent_id, "is_dummy": False, "error": str(e)}

    def handle_webhook(self, payload, signature):
        """Handle Stripe webhook. `payload` must be the RAW request body (str)."""
        if not self.is_configured:
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().handle_webhook(payload, signature)

        if not self.webhook_secret:
            print("❌ STRIPE_WEBHOOK_SECRET not set — rejecting unverified webhook")
            return {"event_type": "invalid_signature", "data": {}, "is_dummy": False}
        if not signature:
            print("❌ Webhook rejected: missing Stripe-Signature header")
            return {"event_type": "invalid_signature", "data": {}, "is_dummy": False}
        try:
            event = stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
        except Exception as e:
            print(f"❌ Stripe webhook signature verification failed: {str(e)}")
            return {"event_type": "invalid_signature", "data": {}, "is_dummy": False, "error": str(e)}

        return self._normalize_event(event)

    def _normalize_event(self, event) -> dict:
        """Map a Stripe event into the shared normalized webhook schema."""
        g = self._get
        event_type = g(event, "type", "unknown")
        data = {}
        try:
            data = g(event, "data") or {}
            data = g(data, "object") or {}
        except Exception:
            data = {}

        if event_type == "payment_intent.succeeded":
            transaction_id = None
            latest_charge = g(data, "latest_charge")
            if latest_charge:
                try:
                    transaction_id = latest_charge if isinstance(latest_charge, str) else g(latest_charge, "id")
                except Exception:
                    transaction_id = None
            payment_method_types = g(data, "payment_method_types") or []
            return {
                "event_type": "payment.succeeded",
                "payment_id": g(data, "id"),
                "transaction_id": transaction_id,
                "payment_method": payment_method_types[0] if payment_method_types and isinstance(payment_method_types, list) else None,
                "refund_id": None,
                "is_dummy": False,
                "data": data,
            }

        if event_type == "charge.refunded":
            refunds = g(g(data, "refunds") or {}, "data") or []
            last = refunds[-1] if refunds else {}
            status = g(last, "status")
            return {
                "event_type": "refund.processed" if status in ("succeeded", "pending", "processing", "requires_action") else "refund.failed",
                "payment_id": g(data, "payment_intent"),
                "transaction_id": None,
                "payment_method": None,
                "refund_id": g(last, "id"),
                "is_dummy": False,
                "data": data,
            }

        if event_type == "refund.updated":
            status = g(data, "status")
            return {
                "event_type": "refund.processed" if status in ("succeeded", "pending", "processing", "requires_action") else "refund.failed",
                "payment_id": g(data, "payment_intent"),
                "transaction_id": None,
                "payment_method": None,
                "refund_id": g(data, "id"),
                "is_dummy": False,
                "data": data,
            }

        # Abandoned / failed intents → webhooks.py cancels the unpaid order & restocks
        if event_type in ("payment_intent.canceled", "payment_intent.payment_failed"):
            return {
                "event_type": "payment.cancelled" if event_type == "payment_intent.canceled" else "payment.failed",
                "payment_id": g(data, "id"),
                "transaction_id": None,
                "payment_method": None,
                "refund_id": None,
                "is_dummy": False,
                "data": data,
            }

        # Any other event — acknowledged, no action
        return {
            "event_type": "unknown",
            "payment_id": g(data, "id"),
            "transaction_id": None,
            "payment_method": None,
            "refund_id": None,
            "is_dummy": False,
            "data": data,
        }

    def refund_payment(self, payment_id):
        """Refund Stripe payment."""
        if not self.is_configured:
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().refund_payment(payment_id)

        try:
            refund = stripe.Refund.create(payment_intent=payment_id)
            return {
                "status": "refunded" if refund.status == "succeeded" else refund.status,
                "refund_id": refund.id,
                "payment_id": payment_id,
                "is_dummy": False,
            }
        except Exception as e:
            print(f"❌ Stripe refund failed: {str(e)}")
            return {"status": "failed", "payment_id": payment_id, "is_dummy": False, "error": str(e)}

    def create_refund(self, payment_id, amount=None, notes=None):
        """
        Create a full or partial refund for a Stripe payment.

        - payment_id: the Stripe PaymentIntent ID (pi_xxx) or Charge ID (ch_xxx)
        - amount:     amount in the configured currency (full unit). None = full refund
        - notes:      dict of notes stored against the refund
        """
        if not self.is_configured:
            from app.services.payment_service import DummyPaymentService
            print("⚠️ Using dummy refund (Stripe not configured)")
            return DummyPaymentService().create_refund(payment_id, amount, notes)

        try:
            params = {}
            if amount is not None:
                params["amount"] = self._amount_in_smallest_unit(amount)
            if notes:
                params["metadata"] = {k: str(v) for k, v in notes.items()}

            # Stripe refunds accept exactly one of `payment_intent` (pi_xxx)
            # or `charge` (ch_xxx). Prefer whichever id is stored on the order:
            # `provider_payment_intent` holds a pi_xxx after /payments/confirm
            # but a ch_xxx when the order was settled by the webhook.
            if payment_id.startswith("ch_"):
                params["charge"] = payment_id
            else:
                params["payment_intent"] = payment_id

            refund = stripe.Refund.create(**params)
            created_status = getattr(refund, "status", "pending")
            print(f"✅ Stripe refund created: {refund.id} (status: {created_status})")

            return {
                "status": created_status,  # succeeded | pending | processing | requires_action | failed
                "refund_id": refund.id,
                "payment_id": payment_id,
                "amount": float(refund.amount) / 100,
                "is_dummy": False,
            }
        except Exception as e:
            print(f"❌ Stripe refund failed: {str(e)}")
            return {"status": "failed", "payment_id": payment_id, "is_dummy": False, "error": str(e)}

    def get_refund_status(self, refund_id):
        """Fetch a refund from Stripe by its refund ID (re_xxx)."""
        if not self.is_configured:
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().get_refund_status(refund_id)

        try:
            refund = stripe.Refund.retrieve(refund_id)
            return {
                "refund_id": refund.id,
                "payment_id": refund.payment_intent,
                "amount": float(refund.amount) / 100,
                "status": getattr(refund, "status", "pending"),  # succeeded | pending | processing | requires_action | failed
                "is_dummy": False,
            }
        except Exception as e:
            print(f"❌ Stripe refund fetch failed: {str(e)}")
            return {"status": "failed", "refund_id": refund_id, "is_dummy": False, "error": str(e)}

    def get_payment_id_for_order(self, payment_intent_id):
        """
        Resolve the actual Charge ID (ch_xxx) for a Stripe PaymentIntent
        (pi_xxx). Returns None if the intent has no successful charge.
        """
        if not self.is_configured:
            return None
    
        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            latest_charge = self._get(intent, "latest_charge")
            if latest_charge:
                return latest_charge if isinstance(latest_charge, str) else self._get(latest_charge, "id")
        except Exception as e:
            print(f"⚠️ Could not fetch charge for Stripe PaymentIntent {payment_intent_id}: {e}")
        return None

    def cancel_payment_intent(self, payment_intent_id):
        """Cancel an unpaid Stripe PaymentIntent (abandoned-order sweep)."""
        if not self.is_configured:
            return {"status": "skipped", "payment_intent_id": payment_intent_id, "is_dummy": False}

        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            status = self._get(intent, "status")
            if status in ("requires_payment_method", "requires_confirmation", "requires_action", "requires_capture", "processing"):
                canceled = stripe.PaymentIntent.cancel(payment_intent_id)
                print(f"🗑️ Stripe PaymentIntent {payment_intent_id} cancelled (was {status})")
                return {"status": self._get(canceled, "status"), "payment_intent_id": payment_intent_id, "is_dummy": False}
            print(f"ℹ️ Skipped cancelling Stripe PaymentIntent {payment_intent_id} — status {status}")
            return {"status": "skipped", "payment_intent_id": payment_intent_id, "is_dummy": False}
        except Exception as e:
            print(f"❌ Stripe cancel failed: {e}")
            return {"status": "failed", "payment_intent_id": payment_intent_id, "is_dummy": False, "error": str(e)}