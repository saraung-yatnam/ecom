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
        self.frontend_url = settings.FRONTEND_URL
        
        # Debug: Check if API key is set
        if self.api_key:
            print(f"SendGrid API Key loaded: {self.api_key[:10]}...")
        else:
            print("WARNING: SENDGRID_API_KEY not found in settings!")

    def format_currency(self, amount: Decimal) -> str:
        return f"₹{amount:,.2f}"

    def _send_email(self, to_email: str, subject: str, html_content: str, plain_text: str = None):
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
            if plain_text:
                message.plain_text_content = plain_text
                
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

    # ========== NEW: Password Reset Email ==========
    def send_password_reset_email(self, user_email: str, user_name: str, reset_token: str):
        """
        Send password reset email to user.
        
        Args:
            user_email: User's email address
            user_name: User's full name or username
            reset_token: The password reset token
        """
        reset_link = f"{self.frontend_url}/reset-password?token={reset_token}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                    background-color: #f6f9fc;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #ffffff;
                }}
                .header {{
                    text-align: center;
                    padding: 30px 0 20px 0;
                    border-bottom: 1px solid #e8e8e8;
                }}
                .header h1 {{
                    color: #1a1a2e;
                    font-size: 28px;
                    margin: 0;
                }}
                .header .logo {{
                    font-size: 32px;
                    font-weight: bold;
                    color: #4f46e5;
                }}
                .content {{
                    padding: 30px 20px;
                }}
                .content p {{
                    color: #4a4a4a;
                    font-size: 16px;
                    line-height: 1.6;
                    margin: 0 0 16px 0;
                }}
                .button-container {{
                    text-align: center;
                    margin: 30px 0;
                }}
                .button {{
                    display: inline-block;
                    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
                    color: #ffffff !important;
                    padding: 14px 40px;
                    border-radius: 8px;
                    text-decoration: none;
                    font-weight: 600;
                    font-size: 16px;
                    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.35);
                    transition: all 0.3s ease;
                }}
                .button:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(79, 70, 229, 0.45);
                }}
                .footer {{
                    border-top: 1px solid #e8e8e8;
                    padding: 20px 20px 0 20px;
                    text-align: center;
                    color: #8c8c8c;
                    font-size: 13px;
                }}
                .footer a {{
                    color: #4f46e5;
                    text-decoration: none;
                }}
                .footer a:hover {{
                    text-decoration: underline;
                }}
                .expiry-notice {{
                    background-color: #f3f4f6;
                    padding: 12px 16px;
                    border-radius: 6px;
                    font-size: 14px;
                    color: #4b5563;
                    margin-top: 20px;
                }}
                .divider {{
                    border: none;
                    border-top: 1px solid #e5e7eb;
                    margin: 24px 0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <span class="logo">🛍️ E-Shop</span>
                    <h1>Reset Your Password</h1>
                </div>
                
                <div class="content">
                    <p>Hi <strong>{user_name}</strong>,</p>
                    
                    <p>We received a request to reset the password for your E-Shop account.</p>
                    
                    <p>Click the button below to create a new password:</p>
                    
                    <div class="button-container">
                        <a href="{reset_link}" class="button">Reset Password</a>
                    </div>
                    
                    <div class="expiry-notice">
                        ⏰ This link will expire in <strong>{settings.RESET_TOKEN_EXPIRE_HOURS} hour(s)</strong>.
                    </div>
                    
                    <hr class="divider">
                    
                    <p style="font-size: 14px; color: #6b7280;">
                        If you didn't request this password reset, please ignore this email. 
                        Your password will remain unchanged.
                    </p>
                    
                    <p style="font-size: 14px; color: #6b7280;">
                        For security reasons, we recommend not sharing this link with anyone.
                    </p>
                </div>
                
                <div class="footer">
                    <p>
                        <strong>E-Shop</strong><br>
                        <span style="color: #9ca3af;">Secure &bull; Reliable &bull; Trusted</span>
                    </p>
                    <p>
                        If you have any issues, contact us at 
                        <a href="mailto:{settings.FROM_EMAIL}">{settings.FROM_EMAIL}</a>
                    </p>
                    <p>&copy; {__import__('datetime').datetime.now().year} E-Shop. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_text = f"""
        Reset Your Password - E-Shop
        
        Hi {user_name},
        
        We received a request to reset the password for your E-Shop account.
        
        Click the link below to reset your password:
        {reset_link}
        
        This link will expire in {settings.RESET_TOKEN_EXPIRE_HOURS} hour(s).
        
        If you didn't request this, please ignore this email.
        
        E-Shop Team
        """
        
        return self._send_email(
            to_email=user_email,
            subject="Reset Your Password - E-Shop",
            html_content=html_content,
            plain_text=plain_text
        )

    # ========== Order Emails ==========
    def send_order_confirmation(self, order: Order, user: User):
        """Send order confirmation email"""
        if not self.client:
            print("SendGrid not configured - skipping email")
            return
        
        subject = f"Order Confirmed - #{order.order_number}"
        
        is_cod = (order.payment_method == "cod")
        cod_fee = order.cod_fee or Decimal("0.00")
        
        items_html = ""
        for item in order.items:
            items_html += f"""
            <tr>
                <td style="padding:10px; border-bottom:1px solid #e5e7eb;">
                    <strong>{item.product_name}</strong><br>
                    <span style="color:#6b7280; font-size:12px;">SKU: {item.variant_sku}</span>
                </td>
                <td style="padding:10px; border-bottom:1px solid #e5e7eb; text-align:center;">{item.quantity}</td>
                <td style="padding:10px; border-bottom:1px solid #e5e7eb; text-align:right;">{self.format_currency(item.unit_price)}</td>
                <td style="padding:10px; border-bottom:1px solid #e5e7eb; text-align:right;"><strong>{self.format_currency(item.line_total)}</strong></td>
            </tr>
            """
        
        # Payment-method banner (the part that was missing entirely)
        if is_cod:
            payment_banner = f"""
            <div style="background-color:#fef3c7; border:2px solid #f59e0b; border-radius:8px; padding:16px 20px; margin:20px 0;">
                <p style="margin:0 0 6px 0; font-size:16px; font-weight:bold; color:#92400e;">
                    💵 Cash on Delivery — keep {self.format_currency(order.grand_total)} ready
                </p>
                <p style="margin:0; font-size:14px; color:#92400e;">
                    Please pay in <strong>cash</strong> when your order arrives.
                    (Includes {self.format_currency(cod_fee)} COD handling fee.)
                </p>
            </div>
            """
        else:
            payment_banner = f"""
            <div style="background-color:#dcfce7; border:2px solid #16a34a; border-radius:8px; padding:16px 20px; margin:20px 0;">
                <p style="margin:0 0 6px 0; font-size:16px; font-weight:bold; color:#166534;">
                    ✅ Payment Received — {self.format_currency(order.grand_total)}
                </p>
                <p style="margin:0; font-size:14px; color:#166534;">
                    Paid online securely via Razorpay. Your order is being processed.
                </p>
            </div>
            """

        cod_fee_row = ""
        if cod_fee > 0:
            cod_fee_row = f"""
                    <tr>
                        <td style="text-align:right; color:#6b7280; border-bottom:none;">COD Fee</td>
                        <td style="text-align:right; border-bottom:none; padding-left:12px;">{self.format_currency(cod_fee)}</td>
                    </tr>"""
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; color: #333; background-color: #f6f9fc; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 24px; }}
                .header {{ background: #2563eb; color: white; padding: 24px 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
                th {{ padding: 10px; text-align: left; background-color: #f3f4f6; border-bottom: 2px solid #e5e7eb; font-size: 13px; text-transform: uppercase; color: #6b7280; }}
                td {{ padding: 10px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
                .meta {{ color: #374151; font-size: 14px; margin: 6px 0; }}
                .footer {{ margin-top: 24px; padding: 20px; text-align: center; color: #9ca3af; font-size: 12px; border-top: 1px solid #e5e7eb; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="margin:0;">Thank You for Your Order! 🎉</h1>
                </div>

                {payment_banner}

                <p class="meta"><strong>Order Number:</strong> #{order.order_number}</p>
                <p class="meta"><strong>Order Date:</strong> {order.placed_at.strftime('%B %d, %Y')}</p>
                <p class="meta"><strong>Payment Method:</strong> {'💵 Cash on Delivery' if is_cod else '💳 Paid Online (Razorpay)'}</p>
                
                <h3>Order Items</h3>
                <table>
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th style="text-align:center;">Qty</th>
                            <th style="text-align:right;">Price</th>
                            <th style="text-align:right;">Total</th>
                        </tr>
                    </thead>
                    <tbody>{items_html}</tbody>
                </table>
                
                <h3>Order Summary</h3>
                <table>
                    <tr>
                        <td style="text-align:right; color:#6b7280; border-bottom:none;">Subtotal</td>
                        <td style="text-align:right; border-bottom:none; padding-left:12px;">{self.format_currency(order.subtotal)}</td>
                    </tr>
                    <tr>
                        <td style="text-align:right; color:#6b7280; border-bottom:none;">Discount</td>
                        <td style="text-align:right; border-bottom:none; padding-left:12px;">-{self.format_currency(order.discount_total)}</td>
                    </tr>
                    <tr>
                        <td style="text-align:right; color:#6b7280; border-bottom:none;">Tax</td>
                        <td style="text-align:right; border-bottom:none; padding-left:12px;">{self.format_currency(order.tax_total)}</td>
                    </tr>
                    <tr>
                        <td style="text-align:right; color:#6b7280; border-bottom:none;">Shipping</td>
                        <td style="text-align:right; border-bottom:none; padding-left:12px;">{self.format_currency(order.shipping_total)}</td>
                    </tr>{cod_fee_row}
                    <tr>
                        <td style="text-align:right; font-size:18px; font-weight:bold; color:#2563eb; border-top:2px solid #2563eb;">Grand Total</td>
                        <td style="text-align:right; font-size:18px; font-weight:bold; color:#2563eb; border-top:2px solid #2563eb; padding-left:12px;">{self.format_currency(order.grand_total)}</td>
                    </tr>
                </table>
                
                <div class="footer">
                    <p>Thank you for shopping with us!</p>
                    <p>Questions about your order? Contact us at {settings.FROM_EMAIL}</p>
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

    def send_refund_completed(self, order: Order, user: User):
        """Send refund completed notification (money has reached the customer)."""
        subject = f"Refund Completed - #{order.order_number}"
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
                <h1>Refund Completed ✅</h1>
            </div>

            <p>Hi {user.full_name or 'Customer'},</p>
            <p>Good news! The refund for your order <strong>#{order.order_number}</strong> has been completed.</p>
            <p><strong>Refund Amount:</strong> {self.format_currency(order.refund_amount or order.grand_total)}</p>
            <p><strong>Refund ID:</strong> {order.refund_id or '-'}</p>

            <p>The money has been credited back to your original payment method. It may take 1-2 days to reflect in your bank account.</p>
            <p>If you have any questions, please contact our support team.</p>

            <div class="footer">
                <p>Thank you for shopping with us!</p>
            </div>
        </body>
        </html>
        """
        self._send_email(user.email, subject, html_content)

    def send_refund_failed(self, order: Order, user: User):
        """Send refund failed notification (needs customer/admin attention)."""
        subject = f"Refund Issue - #{order.order_number}"
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
                <h1>Refund Failed ❌</h1>
            </div>

            <p>Hi {user.full_name or 'Customer'},</p>
            <p>We're sorry, but the refund for your order <strong>#{order.order_number}</strong> could not be processed.</p>
            <p><strong>Refund Amount:</strong> {self.format_currency(order.refund_amount or order.grand_total)}</p>
            <p><strong>Refund ID:</strong> {order.refund_id or '-'}</p>

            <p>Please contact our support team for assistance and we will resolve this at the earliest.</p>

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