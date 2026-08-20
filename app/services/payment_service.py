import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime

from app.models.order import Order
from app.models.payment import PaymentProvider


class PaymentService(ABC):
    """Abstract base class for payment services"""
    
    @abstractmethod
    def create_payment_intent(
        self, 
        order: Order, 
        payment_method: str = "card"
    ) -> dict:
        """Create payment intent"""
        pass
    
    @abstractmethod
    def confirm_payment(self, payment_intent_id: str) -> dict:
        """Confirm payment"""
        pass
    
    @abstractmethod
    def handle_webhook(self, payload: dict, signature: str) -> dict:
        """Handle webhook event"""
        pass
    
    @abstractmethod
    def refund_payment(self, payment_id: str) -> dict:
        """Refund a payment"""
        pass


class DummyPaymentService(PaymentService):
    """
    Dummy payment service for testing - NO REAL PAYMENTS!
    All payments are "succeeded" automatically.
    """
    
    def create_payment_intent(
        self, 
        order: Order, 
        payment_method: str = "card"
    ) -> dict:
        """Create a dummy payment intent"""
        payment_id = f"dummy_pay_{uuid.uuid4().hex[:12]}"
        
        return {
            "client_secret": f"{payment_id}_secret_dummy",
            "payment_intent_id": payment_id,
            "order_id": str(order.id),
            "amount": float(order.grand_total),
            "currency": "INR",
            "is_dummy": True,
            "status": "succeeded",  # Auto-succeed for testing
            "message": "Dummy payment - no real money involved"
        }
    
    def confirm_payment(self, payment_intent_id: str) -> dict:
        """Confirm dummy payment - always succeeds"""
        return {
            "status": "succeeded",
            "payment_intent_id": payment_intent_id,
            "is_dummy": True,
            "message": "Dummy payment confirmed - no real money involved"
        }
    
    def handle_webhook(self, payload: dict, signature: str) -> dict:
        """Handle dummy webhook"""
        return {
            "event_type": "payment.succeeded",
            "data": payload,
            "is_dummy": True
        }
    
    def refund_payment(self, payment_id: str) -> dict:
        """Refund dummy payment"""
        return {
            "status": "refunded",
            "payment_id": payment_id,
            "is_dummy": True,
            "message": "Dummy refund - no real money involved"
        }


def get_payment_service() -> PaymentService:
    """
    Factory function to get payment service.
    Default: Dummy (no real payment)
    """
    provider = os.getenv("PAYMENT_PROVIDER", "dummy")
    
    if provider == "dummy":
        return DummyPaymentService()
    
    elif provider == "razorpay":
        # Import only when needed
        try:
            from app.services.payment_services.razorpay_service import RazorpayPaymentService
            return RazorpayPaymentService()
        except ImportError:
            print("Razorpay not installed. Falling back to dummy.")
            return DummyPaymentService()
    
    elif provider == "stripe":
        try:
            from app.services.payment_services.stripe_service import StripePaymentService
            return StripePaymentService()
        except ImportError:
            print("Stripe not installed. Falling back to dummy.")
            return DummyPaymentService()
    
    else:
        print(f"Unknown provider: {provider}. Falling back to dummy.")
        return DummyPaymentService()