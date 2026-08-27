# app/schemas/order.py
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field, ConfigDict


# =========================================================
# ENUMS
# =========================================================

class OrderStatusEnum(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


# =========================================================
# NESTED SCHEMAS
# =========================================================

class OrderUserRead(BaseModel):
    """Simplified user data for orders"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    full_name: Optional[str] = None
    email: str
    phone: Optional[str] = None


class OrderAddressRead(BaseModel):
    """Simplified address data for orders - MATCHES YOUR ADDRESS MODEL"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    label: Optional[str] = None
    line1: str
    line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str
    is_default: Optional[bool] = None


class AdminOrderAddressRead(OrderAddressRead):
    """Admin address response with user data included"""
    full_name: Optional[str] = None
    phone: Optional[str] = None


class OrderItemRead(BaseModel):
    """Order item schema"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    product_name: str
    variant_sku: str
    variant_attributes: dict
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    created_at: datetime


# =========================================================
# REQUEST SCHEMAS
# =========================================================

class OrderStatusUpdate(BaseModel):
    """Update order status request"""
    status: OrderStatusEnum


# =========================================================
# RESPONSE SCHEMAS
# =========================================================

class OrderRead(BaseModel):
    """Full order response with nested data"""
    model_config = ConfigDict(from_attributes=True)
    
    # Basic Info
    id: UUID
    order_number: str
    user_id: UUID
    
    # Addresses
    shipping_address_id: UUID
    billing_address_id: UUID
    
    # Nested Data
    user: Optional[OrderUserRead] = None
    shipping_address: Optional[AdminOrderAddressRead] = None
    billing_address: Optional[AdminOrderAddressRead] = None
    
    # Pricing
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    shipping_total: Decimal
    grand_total: Decimal
    
    # Status
    status: str
    payment_status: str
    payment_method: Optional[str] = None
    coupon_code: Optional[str] = None
    
    # Timestamps
    placed_at: datetime
    updated_at: datetime
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    
    # Items
    items: List[OrderItemRead] = Field(default_factory=list)


class OrderListRead(BaseModel):
    """Simplified order list for admin"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    order_number: str
    user_id: UUID
    subtotal: Decimal
    grand_total: Decimal
    status: str
    payment_status: Optional[str] = None
    placed_at: datetime
    item_count: int = 0
    
    # Nested user data for list view
    user: Optional[OrderUserRead] = None


class OrderCreate(BaseModel):
    """Create order request"""
    shipping_address_id: UUID
    billing_address_id: UUID
    coupon_code: Optional[str] = None
    payment_method: Optional[str] = None


class OrderUpdate(BaseModel):
    """Update order request"""
    status: Optional[OrderStatusEnum] = None
    payment_status: Optional[str] = None
    shipping_address_id: Optional[UUID] = None
    billing_address_id: Optional[UUID] = None