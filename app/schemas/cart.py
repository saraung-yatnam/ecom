from decimal import Decimal
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


# -------------------------
# Request Schemas
# -------------------------

class AddToCartRequest(BaseModel):
    variant_id: UUID
    quantity: int = Field(ge=1, le=999)


class UpdateCartItemRequest(BaseModel):
    quantity: int = Field(ge=1, le=999)


# -------------------------
# Response Schemas
# -------------------------

class CartItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    variant_id: UUID
    quantity: int
    price_at_add: Decimal
    created_at: datetime
    
    # Additional fields from variant/product (optional)
    variant_sku: str | None = None
    variant_attributes: dict | None = None
    product_name: str | None = None
    product_slug: str | None = None
    product_image: str | None = None


class CartRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    items: list[CartItemRead] = Field(default_factory=list)
    subtotal: Decimal = Field(default=Decimal("0.00"))
    coupon_code: str | None = None
    discount_total: Decimal = Field(default=Decimal("0.00"))
    tax_total: Decimal = Field(default=Decimal("0.00"))
    shipping_total: Decimal = Field(default=Decimal("0.00"))
    total: Decimal = Field(default=Decimal("0.00"))
    item_count: int = Field(default=0)