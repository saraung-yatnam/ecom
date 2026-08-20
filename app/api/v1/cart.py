from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.api.deps import SessionDep, get_current_user
from app.models.cart import Cart, CartItem
from app.models.user import User
from app.repositories import cart as cart_repo
from app.schemas.cart import (
    AddToCartRequest,
    CartRead,
    UpdateCartItemRequest,
)
from app.utils.cart import calculate_cart_total


router = APIRouter(prefix="/cart", tags=["Cart"])


def get_session_id(request: Request) -> str | None:
    """Get session ID from cookie or header"""
    session_id = request.cookies.get("cart_session_id")
    if session_id:
        return session_id
    return request.headers.get("X-Cart-Session-ID")


@router.get("", response_model=CartRead)
def get_cart(
    request: Request,
    session: SessionDep,
    current_user: User | None = Depends(get_current_user),
):
    """
    Get current user's cart.
    
    - Authenticated users: Get their cart
    - Guest users: Get cart from session ID
    """
    session_id = get_session_id(request)
    user_id = current_user.id if current_user else None
    
    cart = cart_repo.get_or_create_cart(session, user_id, session_id)
    cart_with_items = cart_repo.get_cart_with_items(session, cart.id)
    
    # Calculate totals
    totals = calculate_cart_total(cart_with_items)
    
    return CartRead(
        id=cart_with_items.id,
        items=totals["items"],
        subtotal=totals["subtotal"],
        coupon_code=cart_with_items.coupon_code,
        discount_total=totals["discount_total"],
        tax_total=totals["tax_total"],
        shipping_total=totals["shipping_total"],
        total=totals["total"],
        item_count=totals["item_count"]
    )


@router.post("/items", response_model=CartRead, status_code=status.HTTP_201_CREATED)
def add_to_cart(
    request: Request,
    item_data: AddToCartRequest,
    session: SessionDep,
    current_user: User | None = Depends(get_current_user),
):
    """
    Add item to cart.
    
    - If item already exists, quantity is increased
    - Validates stock availability
    """
    session_id = get_session_id(request)
    user_id = current_user.id if current_user else None
    
    cart = cart_repo.get_or_create_cart(session, user_id, session_id)
    
    try:
        cart_repo.add_item_to_cart(session, cart, item_data.variant_id, item_data.quantity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    cart_with_items = cart_repo.get_cart_with_items(session, cart.id)
    totals = calculate_cart_total(cart_with_items)
    
    return CartRead(
        id=cart_with_items.id,
        items=totals["items"],
        subtotal=totals["subtotal"],
        coupon_code=cart_with_items.coupon_code,
        discount_total=totals["discount_total"],
        tax_total=totals["tax_total"],
        shipping_total=totals["shipping_total"],
        total=totals["total"],
        item_count=totals["item_count"]
    )


@router.put("/items/{item_id}", response_model=CartRead)
def update_cart_item(
    item_id: UUID,
    item_data: UpdateCartItemRequest,
    request: Request,
    session: SessionDep,
    current_user: User | None = Depends(get_current_user),
):
    """
    Update cart item quantity.
    """
    # Get cart item
    cart_item = session.get(CartItem, item_id)
    if not cart_item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Check ownership
    cart = session.get(Cart, cart_item.cart_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    
    if current_user:
        if cart.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized")
    else:
        session_id = get_session_id(request)
        if cart.session_id != session_id:
            raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        cart_repo.update_cart_item(session, cart_item, item_data.quantity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    cart_with_items = cart_repo.get_cart_with_items(session, cart.id)
    totals = calculate_cart_total(cart_with_items)
    
    return CartRead(
        id=cart_with_items.id,
        items=totals["items"],
        subtotal=totals["subtotal"],
        coupon_code=cart_with_items.coupon_code,
        discount_total=totals["discount_total"],
        tax_total=totals["tax_total"],
        shipping_total=totals["shipping_total"],
        total=totals["total"],
        item_count=totals["item_count"]
    )


@router.delete("/items/{item_id}", response_model=CartRead)
def remove_from_cart(
    item_id: UUID,
    request: Request,
    session: SessionDep,
    current_user: User | None = Depends(get_current_user),
):
    """
    Remove item from cart.
    """
    # Get cart item
    cart_item = session.get(CartItem, item_id)
    if not cart_item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Check ownership
    cart = session.get(Cart, cart_item.cart_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    
    if current_user:
        if cart.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized")
    else:
        session_id = get_session_id(request)
        if cart.session_id != session_id:
            raise HTTPException(status_code=403, detail="Not authorized")
    
    cart_repo.remove_cart_item(session, cart_item)
    
    cart_with_items = cart_repo.get_cart_with_items(session, cart.id)
    totals = calculate_cart_total(cart_with_items)
    
    return CartRead(
        id=cart_with_items.id,
        items=totals["items"],
        subtotal=totals["subtotal"],
        coupon_code=cart_with_items.coupon_code,
        discount_total=totals["discount_total"],
        tax_total=totals["tax_total"],
        shipping_total=totals["shipping_total"],
        total=totals["total"],
        item_count=totals["item_count"]
    )


@router.delete("", response_model=CartRead)
def clear_cart(
    request: Request,
    session: SessionDep,
    current_user: User | None = Depends(get_current_user),
):
    """
    Clear all items from cart.
    """
    session_id = get_session_id(request)
    user_id = current_user.id if current_user else None
    
    cart = cart_repo.get_or_create_cart(session, user_id, session_id)
    cart_repo.clear_cart(session, cart)
    
    return CartRead(
        id=cart.id,
        items=[],
        subtotal=Decimal("0.00"),
        coupon_code=None,
        discount_total=Decimal("0.00"),
        tax_total=Decimal("0.00"),
        shipping_total=Decimal("0.00"),
        total=Decimal("0.00"),
        item_count=0
    )