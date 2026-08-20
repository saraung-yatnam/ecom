from uuid import UUID
from decimal import Decimal
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict


class CheckoutRequest(BaseModel):
    shipping_address_id: UUID
    billing_address_id: UUID | None = None  # If not provided, use shipping address
    payment_method: str = Field(default="card")  # card, upi, cod


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    order_number: str
    user_id: UUID
    
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    shipping_total: Decimal
    grand_total: Decimal
    
    status: str
    payment_status: str
    
    placed_at: datetime
    shipped_at: datetime | None
    delivered_at: datetime | None


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    product_name: str
    variant_sku: str
    variant_attributes: dict
    quantity: int
    unit_price: Decimal
    line_total: Decimal