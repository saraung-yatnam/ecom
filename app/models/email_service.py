import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail


class EmailService:
    def __init__(self):
        self.api_key = os.getenv("SENDGRID_API_KEY")
        self.from_email = os.getenv("FROM_EMAIL")
        self.client = SendGridAPIClient(self.api_key)
    
    def send_order_confirmation(self, order, user):
        subject = f"Order Confirmed: {order.order_number}"
        html_content = f"""
        <h1>Thank you for your order!</h1>
        <p>Order #: {order.order_number}</p>
        <p>Total: ₹{order.grand_total}</p>
        """
        
        message = Mail(
            from_email=self.from_email,
            to_emails=user.email,
            subject=subject,
            html_content=html_content
        )
        self.client.send(message)
    
    def send_order_shipped(self, order, user):
        # Similar to above
        pass