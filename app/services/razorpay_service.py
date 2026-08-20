import os
from app.services.payment_service import PaymentService


class RazorpayPaymentService(PaymentService):
    """
    Razorpay payment service.
    Replace dummy with actual Razorpay API calls when ready.
    """
    
    def __init__(self):
        self.key_id = os.getenv("RAZORPAY_KEY_ID")
        self.key_secret = os.getenv("RAZORPAY_KEY_SECRET")
        
        if not self.key_id or not self.key_secret:
            print("WARNING: Razorpay keys not set. Falling back to dummy mode.")
            self.is_configured = False
        else:
            self.is_configured = True
            # import razorpay
            # self.client = razorpay.Client(auth=(self.key_id, self.key_secret))
    
    def create_payment_intent(self, order, payment_method="card"):
        """Create Razorpay order"""
        if not self.is_configured:
            # Return dummy if not configured
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().create_payment_intent(order, payment_method)
        
        # Actual Razorpay implementation
        # return self.client.order.create({
        #     "amount": int(order.grand_total * 100),
        #     "currency": "INR",
        #     "receipt": order.order_number,
        #     "payment_capture": 1,
        # })
        pass
    
    def confirm_payment(self, payment_intent_id):
        """Confirm Razorpay payment"""
        if not self.is_configured:
            from app.services.payment_service import DummyPaymentService
            return DummyPaymentService().confirm_payment(payment_intent_id)
        pass
    
    def handle_webhook(self, payload, signature):
        """Handle Razorpay webhook"""
        pass
    
    def refund_payment(self, payment_id):
        """Refund Razorpay payment"""
        pass