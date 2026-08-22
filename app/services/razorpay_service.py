from app.services.payment_service import PaymentService
from app.core.config import settings

# Try to import razorpay
try:
    import razorpay
    RAZORPAY_AVAILABLE = True
except ImportError:
    RAZORPAY_AVAILABLE = False
    print("⚠️ Razorpay not installed. Install with: uv add razorpay")


class RazorpayPaymentService(PaymentService):
    """Razorpay payment service implementation."""
    
    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID
        self.key_secret = settings.RAZORPAY_KEY_SECRET
        self.webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
        
        print(f"Razorpay Available: {RAZORPAY_AVAILABLE}")
        print(f"Razorpay Key ID: {self.key_id}")
        print(f"Razorpay Key Secret: {'***' if self.key_secret else 'None'}")
        
        if not RAZORPAY_AVAILABLE:
            print("❌ Razorpay library not installed. Falling back to dummy.")
            self.is_configured = False
            return
        
        if not self.key_id or not self.key_secret:
            print("❌ Razorpay keys not set. Falling back to dummy.")
            self.is_configured = False
            return
        
        self.is_configured = True
        try:
            self.client = razorpay.Client(auth=(self.key_id, self.key_secret))
            print(f"✅ Razorpay initialized with key: {self.key_id[:10]}...")
        except Exception as e:
            print(f"❌ Razorpay initialization failed: {str(e)}")
            self.is_configured = False
    
    def create_payment_intent(self, order, payment_method="card"):
        """Create Razorpay order"""
        if not self.is_configured:
            from app.services.payment_service import DummyPaymentService
            print("⚠️ Using dummy payment (Razorpay not configured)")
            return DummyPaymentService().create_payment_intent(order, payment_method)
        
        try:
            amount_in_paise = int(float(order.grand_total) * 100)
            
            razorpay_order = self.client.order.create({
                "amount": amount_in_paise,
                "currency": "INR",
                "receipt": order.order_number,
                "payment_capture": 1,
                "notes": {
                    "order_id": str(order.id),
                    "order_number": order.order_number,
                }
            })
            
            print(f"✅ Razorpay order created: {razorpay_order['id']}")
            
            return {
                "client_secret": razorpay_order["id"],
                "payment_intent_id": razorpay_order["id"],
                "order_id": str(order.id),
                "amount": float(order.grand_total),
                "currency": "INR",
                "is_dummy": False,
                "razorpay_order": razorpay_order,
            }
        except Exception as e:
            print(f"❌ Razorpay order creation failed: {str(e)}")
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().create_payment_intent(order, payment_method)
    
    def confirm_payment(self, payment_intent_id):
        """Fetch Razorpay order status"""
        if not self.is_configured:
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().confirm_payment(payment_intent_id)
        
        try:
            order = self.client.order.fetch(payment_intent_id)
            if order["status"] == "paid":
                return {"status": "succeeded", "payment_intent_id": payment_intent_id, "is_dummy": False}
            elif order["status"] == "created":
                return {"status": "pending", "payment_intent_id": payment_intent_id, "is_dummy": False}
            else:
                return {"status": "failed", "payment_intent_id": payment_intent_id, "is_dummy": False}
        except Exception as e:
            print(f"❌ Razorpay order fetch failed: {str(e)}")
            return {"status": "failed", "payment_intent_id": payment_intent_id, "is_dummy": False, "error": str(e)}
    
    def handle_webhook(self, payload, signature):
        """Handle Razorpay webhook"""
        if not self.is_configured:
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().handle_webhook(payload, signature)
        
        try:
            import json
            if self.webhook_secret:
                self.client.utility.verify_webhook_signature(payload, signature, self.webhook_secret)
            
            event = json.loads(payload)
            return {"event_type": event.get("event"), "data": event.get("payload", {}), "is_dummy": False}
        except Exception as e:
            print(f"❌ Razorpay webhook verification failed: {str(e)}")
            return {"event_type": "unknown", "data": {}, "is_dummy": False, "error": str(e)}
    
    def refund_payment(self, payment_id):
        """Refund Razorpay payment"""
        if not self.is_configured:
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().refund_payment(payment_id)
        
        try:
            refund = self.client.payment.refund(payment_id)
            return {"status": "refunded", "refund_id": refund["id"], "payment_id": payment_id, "is_dummy": False}
        except Exception as e:
            print(f"❌ Razorpay refund failed: {str(e)}")
            return {"status": "failed", "payment_id": payment_id, "is_dummy": False, "error": str(e)}