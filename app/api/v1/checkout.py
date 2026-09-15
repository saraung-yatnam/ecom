from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep,CurrentUser
from app.models.cart import Cart
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User
from app.models.address import Address
from app.repositories import cart as cart_repo
from app.repositories import address as address_repo
from app.repositories import coupon as coupon_repo
from app.schemas.checkout import CheckoutConfigResponse, CheckoutRequest, OrderRead
from app.models.coupon import CouponType
from app.utils.cart import validate_cart_items
from app.services.pricing import resolve_cart_pricing
from app.utils.order import generate_order_number
from app.repositories import notification as notification_repo
from app.services.email_service import email_service
from app.core.config import settings


router = APIRouter(prefix="/checkout", tags=["Checkout"])


@router.get("/config", response_model=CheckoutConfigResponse)
def get_checkout_config():
    """
    Client-facing checkout pricing configuration (public — nothing sensitive).

    Production rule ("single source of truth"): these values are display-only
    hints so the storefront doesn't hardcode business rules like the COD fee
    or eligibility limits. The authoritative computation always happens
    server-side in `checkout()` below, which re-reads the same settings,
    re-applies the eligibility guards and persists `cod_fee` on the order row.
    """
    return CheckoutConfigResponse(
        cod_fee=settings.COD_FEE,
        cod_min_order_value=settings.COD_MIN_ORDER_VALUE,
        cod_max_order_value=settings.COD_MAX_ORDER_VALUE,
        free_shipping_threshold=settings.FREE_SHIPPING_THRESHOLD,
        shipping_cost=settings.SHIPPING_COST,
        tax_rate=settings.TAX_RATE,
    )


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def checkout(
    checkout_data: CheckoutRequest,
    session: SessionDep,
    current_user: CurrentUser,
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
    
    # 5-9. Resolve pricing via the central engine (single source of truth).
    # The engine re-validates any manual coupon on the cart AND evaluates
    # automatic coupons against their trigger conditions — checkout is the
    # final authority on whether a discount applies and how large it is.
    pricing = resolve_cart_pricing(session, cart_with_items, current_user)
    subtotal = pricing.subtotal
    print(f"Subtotal: {subtotal}")
    
    winner = pricing.manual or pricing.automatic
    coupon_code = winner.coupon.code if winner else None
    discount_amount = pricing.discount_total
    final_subtotal = pricing.new_subtotal
    
    if winner:
        winner_kind = "automatic" if pricing.manual is None else "manual"
        print(
            f"Coupon applied ({winner_kind}): {coupon_code}, "
            f"discount={discount_amount}, new subtotal: {final_subtotal}"
        )
    
    if cart.coupon_code and pricing.manual is None:
        # Stored manual code is no longer valid — drop it from the cart.
        cart.coupon_code = None
        session.add(cart)
    
    tax_amount = pricing.tax_total
    print(f"Tax amount: {tax_amount}")
    
    shipping_amount = pricing.shipping_total
    print(f"Shipping amount: {shipping_amount}")
    
    grand_total = pricing.total
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
    
    # 12b. Record usage of an AUTOMATIC winning coupon (manual coupons are
    # counted when their code is applied to the cart — unchanged behavior).
    if winner and winner.coupon.coupon_type == CouponType.AUTOMATIC:
        coupon_repo.increment_coupon_usage(session, winner.coupon)
    
    # 13. Commit everything
    session.commit()
    session.refresh(order)
    
    # 13b. Notify managers/admins about the new order (notifications feed)
    try:
        notification_repo.notify_admins_order_placed(session, order)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Failed to create order notifications: {str(e)}")
    
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

