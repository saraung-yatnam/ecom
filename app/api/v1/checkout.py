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
from app.schemas.checkout import CheckoutRequest, OrderRead
from app.utils.cart import calculate_cart_total
from app.utils.order import generate_order_number


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
    
    if not cart_with_items.items:
        raise HTTPException(
            status_code=400,
            detail="Cart is empty"
        )
    
    # 3. Validate stock
    for item in cart_with_items.items:
        variant = item.variant
        if variant.stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough stock for {variant.sku}. Available: {variant.stock}"
            )
    
    # 4. Calculate totals
    totals = calculate_cart_total(cart_with_items)
    
    # 5. Create order
    order_number = generate_order_number()
    order = Order(
        order_number=order_number,
        user_id=current_user.id,
        shipping_address_id=checkout_data.shipping_address_id,
        billing_address_id=checkout_data.billing_address_id or checkout_data.shipping_address_id,
        subtotal=totals["subtotal"],
        discount_total=totals["discount_total"],
        tax_total=totals["tax_total"],
        shipping_total=totals["shipping_total"],
        grand_total=totals["total"],
        status=OrderStatus.PENDING,
        payment_status="pending",
    )
    session.add(order)
    session.flush()
    
    # 6. Create order items & decrement stock
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
    
    # 7. Clear cart
    cart_repo.clear_cart(session, cart_with_items)
    
    # 8. Commit everything
    session.commit()
    session.refresh(order)
    
    return order