import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from decimal import Decimal

from app.models.user import User
from app.models.order import Order
from app.core.config import settings


class EmailService:
    def __init__(self):
        self.api_key = settings.SENDGRID_API_KEY
        self.from_email = settings.FROM_EMAIL
        self.client = SendGridAPIClient(self.api_key) if self.api_key else None
        
        # Debug: Check if API key is set
        if self.api_key:
            print(f"SendGrid API Key loaded: {self.api_key[:10]}...")
        else:
            print("WARNING: SENDGRID_API_KEY not found in settings!")

    def format_currency(self, amount: Decimal) -> str:
        return f"₹{amount:,.2f}"

    def _send_email(self, to_email: str, subject: str, html_content: str):
        """Internal method to send email"""
        if not self.client:
            print(f"SendGrid not configured - skipping email to {to_email}")
            return False
        
        try:
            message = Mail(
                from_email=self.from_email,
                to_emails=to_email,
                subject=subject,
                html_content=html_content
            )
            response = self.client.send(message)
            print(f"Email sent successfully to {to_email} (status: {response.status_code})")
            return response.status_code in (200, 201, 202)
        except Exception as e:
            print(f"Failed to send email to {to_email}: {str(e)}")
            return False

    def send_test_email(self, to_email: str):
        """Send a test email"""
        return self._send_email(
            to_email,
            "Test Email from E-Commerce API",
            "<h1>✅ Test Email</h1><p>If you received this, your email system is working!</p>"
        )

    def send_order_confirmation(self, order: Order, user: User):
        """Send order confirmation email"""
        if not self.client:
            print("SendGrid not configured - skipping email")
            return
        
        subject = f"Order Confirmed - #{order.order_number}"
        
        items_html = ""
        for item in order.items:
            items_html += f"""
            <tr>
                <td>{item.product_name}</td>
                <td>{item.quantity}</td>
                <td>{self.format_currency(item.unit_price)}</td>
                <td>{self.format_currency(item.line_total)}</td>
            </tr>
            """
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #2563eb; color: white; padding: 20px; text-align: center; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
                .total {{ font-size: 20px; font-weight: bold; color: #2563eb; }}
                .footer {{ margin-top: 20px; padding: 20px; text-align: center; color: #888; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Thank You for Your Order! 🎉</h1>
                </div>
                
                <p><strong>Order Number:</strong> {order.order_number}</p>
                <p><strong>Order Date:</strong> {order.placed_at.strftime('%B %d, %Y')}</p>
                
                <h3>Order Items</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Qty</th>
                            <th>Price</th>
                            <th>Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items_html}
                    </tbody>
                </table>
                
                <h3>Order Summary</h3>
                <p><strong>Subtotal:</strong> {self.format_currency(order.subtotal)}</p>
                <p><strong>Discount:</strong> -{self.format_currency(order.discount_total)}</p>
                <p><strong>Tax:</strong> {self.format_currency(order.tax_total)}</p>
                <p><strong>Shipping:</strong> {self.format_currency(order.shipping_total)}</p>
                <p class="total"><strong>Grand Total:</strong> {self.format_currency(order.grand_total)}</p>
                
                <div class="footer">
                    <p>Thank you for shopping with us!</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        self._send_email(user.email, subject, html_content)

    def send_order_shipped(self, order: Order, user: User):
        """Send order shipped notification"""
        subject = f"Your Order Has Been Shipped - #{order.order_number}"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .header {{ background: #16a34a; color: white; padding: 20px; text-align: center; }}
                .footer {{ margin-top: 20px; padding: 20px; text-align: center; color: #888; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>📦 Your Order is On Its Way!</h1>
            </div>
            
            <p>Hi {user.full_name or 'Customer'},</p>
            <p>Your order <strong>#{order.order_number}</strong> has been shipped!</p>
            <p><strong>Total:</strong> {self.format_currency(order.grand_total)}</p>
            
            <div class="footer">
                <p>Thank you for shopping with us!</p>
            </div>
        </body>
        </html>
        """
        self._send_email(user.email, subject, html_content)

    def send_order_delivered(self, order: Order, user: User):
        """Send order delivered notification"""
        subject = f"Your Order Has Been Delivered - #{order.order_number}"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .header {{ background: #16a34a; color: white; padding: 20px; text-align: center; }}
                .footer {{ margin-top: 20px; padding: 20px; text-align: center; color: #888; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>✅ Order Delivered!</h1>
            </div>
            
            <p>Hi {user.full_name or 'Customer'},</p>
            <p>Your order <strong>#{order.order_number}</strong> has been delivered! 🎉</p>
            <p><strong>Total:</strong> {self.format_currency(order.grand_total)}</p>
            
            <div class="footer">
                <p>Thank you for shopping with us!</p>
            </div>
        </body>
        </html>
        """
        self._send_email(user.email, subject, html_content)

    def send_order_cancelled(self, order: Order, user: User):
        """Send order cancelled notification"""
        subject = f"Order Cancelled - #{order.order_number}"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .header {{ background: #dc2626; color: white; padding: 20px; text-align: center; }}
                .footer {{ margin-top: 20px; padding: 20px; text-align: center; color: #888; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Order Cancelled ❌</h1>
            </div>
            
            <p>Hi {user.full_name or 'Customer'},</p>
            <p>Your order <strong>#{order.order_number}</strong> has been cancelled.</p>
            <p><strong>Order Date:</strong> {order.placed_at.strftime('%B %d, %Y')}</p>
            <p><strong>Total:</strong> {self.format_currency(order.grand_total)}</p>
            
            <p>If you have any questions, please contact our support team.</p>
            
            <div class="footer">
                <p>Thank you for shopping with us!</p>
            </div>
        </body>
        </html>
        """
        self._send_email(user.email, subject, html_content)

    def send_order_refunded(self, order: Order, user: User):
        """Send order refunded notification"""
        subject = f"Order Refunded - #{order.order_number}"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .header {{ background: #f59e0b; color: white; padding: 20px; text-align: center; }}
                .footer {{ margin-top: 20px; padding: 20px; text-align: center; color: #888; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Order Refunded 💰</h1>
            </div>
            
            <p>Hi {user.full_name or 'Customer'},</p>
            <p>Your order <strong>#{order.order_number}</strong> has been refunded.</p>
            <p><strong>Order Date:</strong> {order.placed_at.strftime('%B %d, %Y')}</p>
            <p><strong>Refund Amount:</strong> {self.format_currency(order.grand_total)}</p>
            
            <p>The refund will reflect in your account within 3-5 business days.</p>
            <p>If you have any questions, please contact our support team.</p>
            
            <div class="footer">
                <p>Thank you for shopping with us!</p>
            </div>
        </body>
        </html>
        """
        self._send_email(user.email, subject, html_content)

    def send_welcome_email(self, user: User):
        """Send welcome email"""
        subject = f"Welcome to Our Store, {user.full_name or user.username}!"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; }}
                .header {{ background: #2563eb; color: white; padding: 20px; text-align: center; }}
                .footer {{ margin-top: 20px; padding: 20px; text-align: center; color: #888; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Welcome to Our Store! 🎉</h1>
            </div>
            
            <p>Hi {user.full_name or user.username},</p>
            <p>Thank you for joining us! We're excited to have you as a customer.</p>
            
            <p>Here's what you can do:</p>
            <ul>
                <li>🛍️ Browse our products</li>
                <li>❤️ Save items to your wishlist</li>
                <li>📦 Track your orders</li>
            </ul>
            
            <p>Start shopping now!</p>
            
            <div class="footer">
                <p>If you have any questions, feel free to reach out!</p>
            </div>
        </body>
        </html>
        """
        self._send_email(user.email, subject, html_content)


# Singleton instance
email_service = EmailService()