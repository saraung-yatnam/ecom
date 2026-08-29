from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, get_current_user
from app.models.cart import Cart
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User
from app.models.address import Address
from app.repositories import cart as cart_repo
from app.repositories import address as address_repo
from app.repositories import coupon as coupon_repo
from app.schemas.checkout import CheckoutRequest, OrderRead
from app.utils.cart import calculate_cart_total, validate_cart_items, calculate_tax, calculate_shipping
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
    
    # 1. Validate shipping address exists
    shipping_address = address_repo.get_address_by_id(
        session, checkout_data.shipping_address_id
    )
    if not shipping_address or shipping_address.user_id != current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Invalid shipping address"
        )
    
    # 2. Handle billing address
    billing_address_id = checkout_data.billing_address_id
    if checkout_data.billing_address_id:
        billing_address = address_repo.get_address_by_id(
            session, checkout_data.billing_address_id
        )
        if not billing_address or billing_address.user_id != current_user.id:
            raise HTTPException(
                status_code=400,
                detail="Invalid billing address"
            )
    else:
        billing_address_id = checkout_data.shipping_address_id
    
    # 3. Get user's cart
    cart = cart_repo.get_or_create_cart(session, current_user.id)
    cart_with_items = cart_repo.get_cart_with_items(session, cart.id)
    
    if not cart_with_items.items:
        raise HTTPException(
            status_code=400,
            detail="Cart is empty"
        )
    
    # 4. Validate stock
    validation = validate_cart_items(cart_with_items)
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail="; ".join(validation["errors"])
        )
    
    # 5. Calculate subtotal
    subtotal = Decimal("0.00")
    for item in cart_with_items.items:
        subtotal += item.price_at_add * item.quantity
    
    print(f"Subtotal: {subtotal}")
    
    # 6. Process coupon
    coupon_code = None
    discount_amount = Decimal("0.00")
    final_subtotal = subtotal
    
    if cart.coupon_code:
        coupon = coupon_repo.get_coupon_by_code(session, cart.coupon_code)
        if coupon:
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
            if is_valid:
                coupon_code = cart.coupon_code
                discount_amount, final_subtotal = calc_discount(coupon, subtotal)
                print(f"Coupon applied: {discount_amount}, new subtotal: {final_subtotal}")
            else:
                # Remove invalid coupon from cart
                cart.coupon_code = None
                session.add(cart)
    
    # 7. Calculate tax using utils ✅
    tax_amount = calculate_tax(cart_with_items)
    print(f"Tax amount: {tax_amount}")
    
    # 8. Calculate shipping using utils ✅
    shipping_amount = calculate_shipping(cart_with_items)
    print(f"Shipping amount: {shipping_amount}")
    
    # 9. Calculate grand total
    grand_total = final_subtotal + tax_amount + shipping_amount
    print(f"Grand total: {grand_total}")
    
    # 9.5 Resolve payment method from checkout body (persisted on the order)
    payment_method = checkout_data.payment_method.value  # cod | online
    
    # 10. COD (Cash on Delivery) handling
    cod_fee = Decimal("0.00")
    if payment_method == "cod":
        # Industry-standard eligibility guards
        if grand_total < Decimal(str(settings.COD_MIN_ORDER_VALUE)):
            raise HTTPException(
                status_code=400,
                detail=f"Cash on Delivery is available only for orders of ₹{settings.COD_MIN_ORDER_VALUE:g} or more",
            )
        if grand_total > Decimal(str(settings.COD_MAX_ORDER_VALUE)):
            raise HTTPException(
                status_code=400,
                detail=f"Cash on Delivery is available only for orders up to ₹{settings.COD_MAX_ORDER_VALUE:g}. Please pay online.",
            )
        cod_fee = Decimal(str(settings.COD_FEE))
        grand_total += cod_fee
        print(f"COD order: fee={cod_fee}, payable on delivery={grand_total}")
    
    # 10. Create order
    order_number = generate_order_number()
    print(f"Order number: {order_number}")
    
    order = Order(
        order_number=order_number,
        user_id=current_user.id,
        shipping_address_id=checkout_data.shipping_address_id,
        billing_address_id=billing_address_id,
        subtotal=final_subtotal,
        discount_total=discount_amount,
        tax_total=tax_amount,
        shipping_total=shipping_amount,
        cod_fee=cod_fee,
        grand_total=grand_total,
        coupon_code=coupon_code,
        payment_method=payment_method,
        # COD orders are confirmed immediately (cash collected on delivery);
        # prepaid orders wait for the payment intent flow
        status=OrderStatus.CONFIRMED if payment_method == "cod" else OrderStatus.PENDING,
        payment_status="cod_pending" if payment_method == "cod" else "pending",
    )
    session.add(order)
    session.flush()
    
    # 11. Create order items & decrement stock
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
    
    # 12. Clear cart
    cart_repo.clear_cart(session, cart_with_items)
    
    # 13. Commit everything
    session.commit()
    session.refresh(order)
    
    # 14. Send order confirmation email
    #     - COD: order is fully confirmed at checkout -> "pay on delivery" email now
    #     - Online: email is sent after payment succeeds (payments.py / webhooks.py)
    if payment_method == "cod" and settings.SENDGRID_API_KEY:
        try:
            user = session.get(User, order.user_id)
            if user:
                email_service.send_order_confirmation(order, user)
                print(f"Order confirmation email sent to {user.email}")
        except Exception as e:
            print(f"Failed to send order confirmation email: {str(e)}")
    
    print("="*50)
    print(f"FINAL ORDER: payment_method={payment_method}, cod_fee={order.cod_fee}, coupon_code={order.coupon_code}, grand_total={order.grand_total}")
    print("=== CHECKOUT DEBUG END ===")
    print("="*50 + "\n")
    
    return order