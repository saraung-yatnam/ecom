import uuid
from abc import ABC, abstractmethod

from app.models.order import Order
from app.core.config import settings  # 👈 Use settings


class PaymentService(ABC):
    """Abstract base class for payment services"""
    
    @abstractmethod
    def create_payment_intent(self, order: Order, payment_method: str = "card") -> dict:
        pass
    
    @abstractmethod
    def confirm_payment(self, payment_intent_id: str) -> dict:
        pass
    
    @abstractmethod
    def handle_webhook(self, payload: dict, signature: str) -> dict:
        pass
    
    @abstractmethod
    def refund_payment(self, payment_id: str) -> dict:
        pass

    @abstractmethod
    def create_refund(
        self,
        payment_id: str,
        amount: float | None = None,
        notes: dict | None = None,
    ) -> dict:
        """Create a full or partial refund for a payment."""
        pass

    @abstractmethod
    def get_refund_status(self, refund_id: str) -> dict:
        """Fetch the status of a refund."""
        pass

    def get_payment_id_for_order(self, razorpay_order_id: str) -> str | None:
        """Resolve the provider payment (pay_xxx) for an order id.

        Base implementation returns None; providers that support it override
        this. Currently only Razorpay implements it.
        """
        return None


class DummyPaymentService(PaymentService):
    """Dummy payment service for testing"""
    
    def create_payment_intent(self, order, payment_method="card") -> dict:
        payment_id = f"dummy_pay_{uuid.uuid4().hex[:12]}"
        return {
            "client_secret": f"{payment_id}_secret_dummy",
            "payment_intent_id": payment_id,
            "order_id": str(order.id),
            "amount": float(order.grand_total),
            "currency": "INR",
            "is_dummy": True,
            "status": "succeeded",
            "message": "Dummy payment - no real money involved"
        }
    
    def confirm_payment(self, payment_intent_id: str) -> dict:
        return {
            "status": "succeeded",
            "payment_intent_id": payment_intent_id,
            "transaction_id": f"dummy_txn_{uuid.uuid4().hex[:12]}",
            "is_dummy": True,
            "message": "Dummy payment confirmed"
        }

    def get_payment_id_for_order(self, razorpay_order_id: str) -> str | None:
        return f"dummy_txn_{uuid.uuid4().hex[:12]}"
    
    def handle_webhook(self, payload, signature: str) -> dict:
        """Dummy webhook handler.

        Reads the event type from the JSON body so local testing can simulate
        any event (payment.succeeded, refund.processed, refund.failed, ...).
        Falls back to ``payment.succeeded`` when no event is provided.
        """
        import json

        body = {}
        if isinstance(payload, str):
            try:
                body = json.loads(payload or "{}")
            except json.JSONDecodeError:
                body = {}
        elif isinstance(payload, dict):
            body = payload

        event_type = body.get("event") or body.get("event_type") or "payment.succeeded"
        return {
            "event_type": event_type,
            "data": body,
            "is_dummy": True,
        }
    
    def refund_payment(self, payment_id: str) -> dict:
        return {
            "status": "refunded",
            "payment_id": payment_id,
            "is_dummy": True
        }

    def create_refund(
        self,
        payment_id: str,
        amount: float | None = None,
        notes: dict | None = None,
    ) -> dict:
        refund_id = f"dummy_rfnd_{uuid.uuid4().hex[:12]}"
        return {
            "status": "processed",
            "refund_id": refund_id,
            "payment_id": payment_id,
            "amount": float(amount or 0),
            "is_dummy": True,
            "message": "Dummy refund - no real money involved",
        }

    def get_refund_status(self, refund_id: str) -> dict:
        return {
            "refund_id": refund_id,
            "status": "processed",
            "is_dummy": True,
            "message": "Dummy refund status",
        }


def get_payment_service() -> PaymentService:
    """Factory function to get payment service"""
    provider = settings.PAYMENT_PROVIDER  # 👈 Use settings
    is_production = settings.ENVIRONMENT == "production"

    print(f"Payment Provider from settings: {provider}")
    print(f"Environment: {settings.ENVIRONMENT}")

    if not provider:
        # No provider configured — a configuration error, never silently pay.
        raise RuntimeError("PAYMENT_PROVIDER is not set")

    if provider == "dummy":
        if is_production:
            raise RuntimeError(
                "PAYMENT_PROVIDER is 'dummy' in production — customers would pay "
                "without any real money being collected. Set it to 'razorpay'."
            )
        print("Using DUMMY payment service")
        return DummyPaymentService()

    elif provider == "razorpay":
        try:
            from app.services.razorpay_service import RazorpayPaymentService
            service = RazorpayPaymentService()
            if hasattr(service, 'is_configured') and service.is_configured:
                print("✅ Using RAZORPAY payment service")
                return service
            if is_production:
                raise RuntimeError(
                    "Razorpay is not configured but ENVIRONMENT=production. "
                    "Refusing to fall back to dummy payments."
                )
            print("⚠️ Razorpay not configured. Falling back to DUMMY.")
            return DummyPaymentService()
        except RuntimeError:
            raise
        except Exception as e:
            if is_production:
                raise RuntimeError(f"Failed to initialize Razorpay: {str(e)}")
            print(f"❌ Error initializing Razorpay: {str(e)}")
            return DummyPaymentService()

    elif provider == "stripe":
        if is_production:
            raise RuntimeError("PAYMENT_PROVIDER='stripe' is not supported in production. Use 'razorpay'.")
        try:
            from app.services.stripe_service import StripePaymentService
            return StripePaymentService()
        except ImportError:
            print("Stripe not installed. Falling back to dummy.")
            return DummyPaymentService()

    else:
        if is_production:
            raise RuntimeError(f"Unknown PAYMENT_PROVIDER: {provider}")
        print(f"Unknown provider: {provider}. Falling back to dummy.")
        return DummyPaymentService()