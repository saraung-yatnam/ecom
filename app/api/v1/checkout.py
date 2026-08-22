from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, get_current_user
from app.models.cart import Cart
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User
from app.repositories import cart as cart_repo
from app.repositories import address as address_repo
from app.repositories import coupon as coupon_repo
from app.schemas.checkout import CheckoutRequest, OrderRead
from app.utils.cart import calculate_cart_total
from app.utils.coupon import validate_coupon, calculate_discount as calc_discount
from app.utils.order import generate_order_number
from app.services.email_service import email_service
from app.core.config import settings


router = APIRouter(prefix="/checkout", tags=["Checkout"])


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def checkout(
    checkout_data: CheckoutRequest,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """
    Convert cart to order.
    """
    
    print("\n" + "="*50)
    print("=== CHECKOUT DEBUG START ===")
    print("="*50)
    
    # 1. Validate addresses exist
    shipping_address = address_repo.get_address_by_id(
        session, checkout_data.shipping_address_id
    )
    if not shipping_address or shipping_address.user_id != current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Invalid shipping address"
        )
    
    if checkout_data.billing_address_id:
        billing_address = address_repo.get_address_by_id(
            session, checkout_data.billing_address_id
        )
        if not billing_address or billing_address.user_id != current_user.id:
            raise HTTPException(
                status_code=400,
                detail="Invalid billing address"
            )
    
    # 2. Get user's cart
    cart = cart_repo.get_or_create_cart(session, current_user.id)
    cart_with_items = cart_repo.get_cart_with_items(session, cart.id)
    
    print(f"1. cart.id: {cart.id}")
    print(f"2. cart.coupon_code: {cart.coupon_code}")
    print(f"3. cart_with_items.coupon_code: {cart_with_items.coupon_code}")
    
    if not cart_with_items.items:
        raise HTTPException(
            status_code=400,
            detail="Cart is empty"
        )
    
    print(f"4. Items in cart: {len(cart_with_items.items)}")
    
    # 3. Validate stock
    for item in cart_with_items.items:
        variant = item.variant
        if variant.stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough stock for {variant.sku}. Available: {variant.stock}"
            )
    
    # 4. Calculate subtotal
    subtotal = Decimal("0.00")
    for item in cart_with_items.items:
        subtotal += item.price_at_add * item.quantity
    
    print(f"5. Subtotal: {subtotal}")
    
    # 5. Check for coupon on cart
    coupon_code = None
    discount_amount = Decimal("0.00")
    final_subtotal = subtotal
    
    print(f"6. Checking if cart.coupon_code exists: {cart.coupon_code}")
    
    if cart.coupon_code:
        print(f"7. Found coupon_code on cart: {cart.coupon_code}")
        coupon = coupon_repo.get_coupon_by_code(session, cart.coupon_code)
        print(f"8. Coupon retrieved from DB: {coupon}")
        
        if coupon:
            print(f"9. Coupon details: code={coupon.code}, value={coupon.value}, type={coupon.discount_type}")
            
            # Validate coupon
            is_valid, message = validate_coupon(
                coupon,
                subtotal,
                current_user.id,
                coupon_repo.get_user_coupon_usage_count(
                    session, 
                    cart.coupon_code, 
                    current_user.id
                )
            )
            print(f"10. Validation result: is_valid={is_valid}, message={message}")
            
            if is_valid:
                coupon_code = cart.coupon_code
                discount_amount, final_subtotal = calc_discount(coupon, subtotal)
                print(f"11. Discount applied: {discount_amount}, new subtotal: {final_subtotal}")
            else:
                print(f"11b. Coupon invalid, removing from cart")
                # Coupon invalid - remove it from cart
                cart.coupon_code = None
                session.add(cart)
        else:
            print(f"9b. Coupon NOT found in database! code: {cart.coupon_code}")
    else:
        print(f"7b. No coupon_code found on cart")
    
    # 6. Calculate tax on discounted amount
    tax_amount = final_subtotal * Decimal("0.18")
    print(f"12. Tax amount: {tax_amount}")
    
    # 7. Calculate shipping
    shipping_amount = Decimal("0.00")
    if final_subtotal == Decimal("0.00"):
        shipping_amount = Decimal("0.00")
    elif final_subtotal >= Decimal("1000.00"):
        shipping_amount = Decimal("0.00")
    else:
        shipping_amount = Decimal("50.00")
    print(f"13. Shipping amount: {shipping_amount}")
    
    # 8. Calculate grand total
    grand_total = final_subtotal + tax_amount + shipping_amount
    print(f"14. Grand total: {grand_total}")
    
    # 9. Create order
    order_number = generate_order_number()
    print(f"15. Order number: {order_number}")
    
    order = Order(
        order_number=order_number,
        user_id=current_user.id,
        shipping_address_id=checkout_data.shipping_address_id,
        billing_address_id=checkout_data.billing_address_id or checkout_data.shipping_address_id,
        subtotal=final_subtotal,
        discount_total=discount_amount,
        tax_total=tax_amount,
        shipping_total=shipping_amount,
        grand_total=grand_total,
        coupon_code=coupon_code,
        status=OrderStatus.PENDING,
        payment_status="pending",
    )
    session.add(order)
    session.flush()
    
    print(f"16. Order created with coupon_code: {order.coupon_code}")
    
    # 10. Create order items & decrement stock
    for item in cart_with_items.items:
        variant = item.variant
        product = variant.product
        
        order_item = OrderItem(
            order_id=order.id,
            variant_id=variant.id,
            product_name=product.name,
            variant_sku=variant.sku,
            variant_attributes=variant.attributes,
            quantity=item.quantity,
            unit_price=item.price_at_add,
            line_total=item.price_at_add * item.quantity,
        )
        session.add(order_item)
        
        # Decrement stock
        variant.stock -= item.quantity
        session.add(variant)
    
    # 11. Clear cart
    cart_repo.clear_cart(session, cart_with_items)
    
    # 12. Commit everything
    session.commit()
    session.refresh(order)
    
    # 13. Send order confirmation email
    if settings.SENDGRID_API_KEY:
        try:
            user = session.get(User, order.user_id)
            if user:
                email_service.send_order_confirmation(order, user)
                print(f"Order confirmation email sent to {user.email}")
        except Exception as e:
            print(f"Failed to send order confirmation email: {str(e)}")
    
    print("="*50)
    print(f"FINAL ORDER: coupon_code={order.coupon_code}, grand_total={order.grand_total}")
    print("=== CHECKOUT DEBUG END ===")
    print("="*50 + "\n")
    
    return order