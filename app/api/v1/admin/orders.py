# app/api/v1/admin/orders.py
from uuid import UUID
from datetime import date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.api.deps import SessionDep, require_role
from app.models.user import User, UserRole
from app.repositories import order as order_repo
from app.schemas.order import OrderRead, OrderStatusUpdate, OrderListRead
from app.services.email_service import email_service
from app.core.config import settings

router = APIRouter(prefix="/admin/orders", tags=["Admin Orders"])


@router.get("", response_model=dict)
def get_all_orders_admin(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    search: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
):
    """
    Get all orders with filters and pagination.
    
    Allowed:
        manager
        admin
    """
    skip = (page - 1) * limit
    
    orders, total = order_repo.get_all_orders_with_filters(
        session=session,
        skip=skip,
        limit=limit,
        status=status,
        search=search,
        from_date=from_date,
        to_date=to_date,
    )
    
    # Manually convert orders to dict with user data
    orders_data = []
    for order in orders:
        # Get user data
        user_data = None
        if order.user:
            user_data = {
                "id": str(order.user.id),
                "full_name": order.user.full_name,
                "email": order.user.email,
                "phone": order.user.phone
            }
        
        # Get shipping address data
        shipping_address_data = None
        if order.shipping_address:
            shipping_address_data = {
                "id": str(order.shipping_address.id),
                "label": order.shipping_address.label,
                "line1": order.shipping_address.line1,
                "line2": order.shipping_address.line2,
                "city": order.shipping_address.city,
                "state": order.shipping_address.state,
                "postal_code": order.shipping_address.postal_code,
                "country": order.shipping_address.country,
                "is_default": order.shipping_address.is_default,
                "full_name": order.user.full_name if order.user else None,
                "phone": order.user.phone if order.user else None
            }
        
        # Get billing address data
        billing_address_data = None
        if order.billing_address:
            billing_address_data = {
                "id": str(order.billing_address.id),
                "label": order.billing_address.label,
                "line1": order.billing_address.line1,
                "line2": order.billing_address.line2,
                "city": order.billing_address.city,
                "state": order.billing_address.state,
                "postal_code": order.billing_address.postal_code,
                "country": order.billing_address.country,
                "is_default": order.billing_address.is_default,
                "full_name": order.user.full_name if order.user else None,
                "phone": order.user.phone if order.user else None
            }
        
        # Build order dictionary
        order_dict = {
            "id": str(order.id),
            "order_number": order.order_number,
            "user_id": str(order.user_id),
            
            # User data
            "user": user_data,
            
            # Address data
            "shipping_address": shipping_address_data,
            "billing_address": billing_address_data,
            "shipping_address_id": str(order.shipping_address_id),
            "billing_address_id": str(order.billing_address_id),
            
            # Financials
            "subtotal": float(order.subtotal) if order.subtotal else 0,
            "discount_total": float(order.discount_total) if order.discount_total else 0,
            "tax_total": float(order.tax_total) if order.tax_total else 0,
            "shipping_total": float(order.shipping_total) if order.shipping_total else 0,
            "grand_total": float(order.grand_total) if order.grand_total else 0,
            
            # Status
            "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
            "payment_status": order.payment_status,
            "coupon_code": order.coupon_code,
            
            # Cancellation
            "cancellation_reason": order.cancellation_reason,
            "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
            
            # Timestamps
            "placed_at": order.placed_at.isoformat() if order.placed_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
            "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
            
            # Items
            "items": [
                {
                    "id": str(item.id),
                    "product_name": item.product_name,
                    "variant_sku": item.variant_sku,
                    "variant_attributes": item.variant_attributes,
                    "quantity": item.quantity,
                    "unit_price": float(item.unit_price) if item.unit_price else 0,
                    "line_total": float(item.line_total) if item.line_total else 0,
                    "created_at": item.created_at.isoformat() if item.created_at else None
                }
                for item in (order.items or [])
            ]
        }
        orders_data.append(order_dict)
    
    return {
        "orders": orders_data,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit,
        }
    }


@router.get("/stats", response_model=dict)
def get_order_stats(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """
    Get order statistics.
    
    Allowed:
        manager
        admin
    """
    return order_repo.get_order_statistics(session)


@router.get("/{order_id}", response_model=dict)
def get_order_detail(
    order_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """
    Get detailed order information.
    
    Allowed:
        manager
        admin
    """
    order = order_repo.get_order_by_id(session, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    # Build response manually
    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "user_id": str(order.user_id),
        
        # User data
        "user": {
            "id": str(order.user.id),
            "full_name": order.user.full_name,
            "email": order.user.email,
            "phone": order.user.phone
        } if order.user else None,
        
        # Shipping address
        "shipping_address": {
            "id": str(order.shipping_address.id),
            "label": order.shipping_address.label,
            "line1": order.shipping_address.line1,
            "line2": order.shipping_address.line2,
            "city": order.shipping_address.city,
            "state": order.shipping_address.state,
            "postal_code": order.shipping_address.postal_code,
            "country": order.shipping_address.country,
            "is_default": order.shipping_address.is_default,
            "full_name": order.user.full_name if order.user else None,
            "phone": order.user.phone if order.user else None
        } if order.shipping_address else None,
        
        # Billing address
        "billing_address": {
            "id": str(order.billing_address.id),
            "label": order.billing_address.label,
            "line1": order.billing_address.line1,
            "line2": order.billing_address.line2,
            "city": order.billing_address.city,
            "state": order.billing_address.state,
            "postal_code": order.billing_address.postal_code,
            "country": order.billing_address.country,
            "is_default": order.billing_address.is_default,
            "full_name": order.user.full_name if order.user else None,
            "phone": order.user.phone if order.user else None
        } if order.billing_address else None,
        
        "shipping_address_id": str(order.shipping_address_id),
        "billing_address_id": str(order.billing_address_id),
        
        # Financials
        "subtotal": float(order.subtotal),
        "discount_total": float(order.discount_total),
        "tax_total": float(order.tax_total),
        "shipping_total": float(order.shipping_total),
        "grand_total": float(order.grand_total),
        
        # Status
        "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "cod_fee": float(order.cod_fee) if order.cod_fee is not None else 0.0,
        "coupon_code": order.coupon_code,
        
        # Cancellation
        "cancellation_reason": order.cancellation_reason,
        "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
        
        # Timestamps
        "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        
        # Items
        "items": [
            {
                "id": str(item.id),
                "product_name": item.product_name,
                "variant_sku": item.variant_sku,
                "variant_attributes": item.variant_attributes,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "line_total": float(item.line_total),
                "created_at": item.created_at.isoformat() if item.created_at else None
            }
            for item in (order.items or [])
        ]
    }


@router.put("/{order_id}/status", response_model=OrderRead)
def update_order_status_admin(
    order_id: UUID,
    status_data: OrderStatusUpdate,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """
    Update order status.
    
    Allowed:
        manager
        admin
    """
    order = order_repo.get_order_by_id(session, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )
    
    old_status = order.status
    new_status = status_data.status.value
    order = order_repo.update_order_status(session, order, new_status)
    
    # Send email notification on status change
    if settings.SENDGRID_API_KEY:
        try:
            user = session.get(User, order.user_id)
            if user:
                if new_status == "shipped" and old_status != "shipped":
                    email_service.send_order_shipped(order, user)
                    print(f"Order shipped email sent to {user.email}")
                elif new_status == "delivered" and old_status != "delivered":
                    email_service.send_order_delivered(order, user)
                    print(f"Order delivered email sent to {user.email}")
                elif new_status == "cancelled" and old_status != "cancelled":
                    email_service.send_order_cancelled(order, user)
                    print(f"Order cancelled email sent to {user.email}")
                elif new_status == "refunded" and old_status != "refunded":
                    email_service.send_order_refunded(order, user)
                    print(f"Order refunded email sent to {user.email}")
        except Exception as e:
            print(f"Failed to send order status email: {str(e)}")
    
    return order