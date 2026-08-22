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
            "is_dummy": True,
            "message": "Dummy payment confirmed"
        }
    
    def handle_webhook(self, payload: dict, signature: str) -> dict:
        return {
            "event_type": "payment.succeeded",
            "data": payload,
            "is_dummy": True
        }
    
    def refund_payment(self, payment_id: str) -> dict:
        return {
            "status": "refunded",
            "payment_id": payment_id,
            "is_dummy": True
        }


def get_payment_service() -> PaymentService:
    """Factory function to get payment service"""
    provider = settings.PAYMENT_PROVIDER  # 👈 Use settings
    
    print(f"Payment Provider from settings: {provider}")
    
    if provider == "dummy":
        print("Using DUMMY payment service")
        return DummyPaymentService()
    
    elif provider == "razorpay":
        try:
            from app.services.razorpay_service import RazorpayPaymentService
            service = RazorpayPaymentService()
            if hasattr(service, 'is_configured') and service.is_configured:
                print("✅ Using RAZORPAY payment service")
                return service
            else:
                print("⚠️ Razorpay not configured. Falling back to DUMMY.")
                return DummyPaymentService()
        except Exception as e:
            print(f"❌ Error initializing Razorpay: {str(e)}")
            return DummyPaymentService()
    
    elif provider == "stripe":
        try:
            from app.services.stripe_service import StripePaymentService
            return StripePaymentService()
        except ImportError:
            print("Stripe not installed. Falling back to dummy.")
            return DummyPaymentService()
    
    else:
        print(f"Unknown provider: {provider}. Falling back to dummy.")
        return DummyPaymentService()