from datetime import datetime
from decimal import Decimal
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict


# Enum for schema validation
class OrderStatusEnum(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


# -------------------------
# Order Status Update (Admin)
# -------------------------

class OrderStatusUpdate(BaseModel):
    status: OrderStatusEnum


# -------------------------
# Order Item Schemas
# -------------------------

class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    product_name: str
    variant_sku: str
    variant_attributes: dict
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    created_at: datetime


# -------------------------
# Order Schemas
# -------------------------

class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    order_number: str
    user_id: UUID
    
    shipping_address_id: UUID
    billing_address_id: UUID
    
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    shipping_total: Decimal
    grand_total: Decimal
    
    status: str
    payment_status: str
    
    placed_at: datetime
    updated_at: datetime
    shipped_at: datetime | None
    delivered_at: datetime | None
    
    items: list[OrderItemRead] = Field(default_factory=list)


class OrderListRead(BaseModel):
    """Simplified order list for admin"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    order_number: str
    user_id: UUID
    subtotal: Decimal
    grand_total: Decimal
    status: str
    placed_at: datetime
    item_count: int = 0