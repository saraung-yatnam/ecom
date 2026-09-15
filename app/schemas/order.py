# app/schemas/order.py
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from enum import Enum
from typing import Any, Optional, List

from pydantic import BaseModel, Field, ConfigDict, model_validator


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
    """Order item schema

    ``product_id``, ``product_slug`` and ``product_image`` are NOT stored on
    the order-item snapshot — they are resolved live from the linked variant's
    product (item -> variant -> product -> images) while serializing.
    ``product_image`` is the product's first image (lowest ``sort_order``).
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_name: str
    variant_sku: str
    variant_attributes: dict
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    created_at: datetime

    # Product info resolved from the variant's product (not part of the snapshot)
    product_id: Optional[UUID] = None
    product_slug: Optional[str] = None
    product_image: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _resolve_product_info(cls, data: Any) -> Any:
        """Resolve product slug + first image when validating an ORM OrderItem.

        Order items are purchase-time snapshots (name / sku / attributes); the
        slug and images live on the parent product, so they are read through
        the relationship chain item -> variant -> product -> images.
        """
        if isinstance(data, dict):
            return data  # plain dicts are used as-is (tests / manual payloads)

        item: dict = {
            "id": getattr(data, "id", None),
            "product_name": getattr(data, "product_name", None),
            "variant_sku": getattr(data, "variant_sku", None),
            "variant_attributes": getattr(data, "variant_attributes", None),
            "quantity": getattr(data, "quantity", None),
            "unit_price": getattr(data, "unit_price", None),
            "line_total": getattr(data, "line_total", None),
            "created_at": getattr(data, "created_at", None),
            # Defaults — stay None when the variant/product is missing
            "product_id": None,
            "product_slug": None,
            "product_image": None,
        }

        variant = getattr(data, "variant", None)
        product = getattr(variant, "product", None) if variant is not None else None
        if product is not None:
            item["product_id"] = product.id
            item["product_slug"] = product.slug
            images = getattr(product, "images", None) or []
            if images:
                # "First" image = lowest sort_order (oldest created_at breaks ties)
                first = min(images, key=lambda img: (img.sort_order, img.created_at))
                item["product_image"] = first.url

        return item


# =========================================================
# REQUEST SCHEMAS
# =========================================================

class OrderStatusUpdate(BaseModel):
    """Update order status request"""
    status: OrderStatusEnum


class CancelOrderRequest(BaseModel):
    """Cancel order request body — reason is optional"""
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Why the order is being cancelled",
    )


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
    
    # Payment transaction
    transaction_id: Optional[str] = None
    
    # Status
    status: str
    payment_status: str
    payment_method: Optional[str] = None
    coupon_code: Optional[str] = None
    
    # Cancellation
    cancellation_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None

    # Refund
    refund_amount: Decimal = Decimal(0)
    refund_id: Optional[str] = None
    refund_reason: Optional[str] = None
    restocking_fee: Decimal = Decimal(0)
    refunded_at: Optional[datetime] = None

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


# =========================================================
# REFUND / CANCELLATION RESPONSE SCHEMAS
# =========================================================

class RefundInfo(BaseModel):
    """Refund details returned alongside a cancellation"""
    processed: bool = False
    amount: Decimal = Decimal(0)
    restocking_fee: Decimal = Decimal(0)
    fee_percentage: Decimal = Decimal(0)
    refund_id: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None


class CancelOrderResponse(BaseModel):
    """Response returned after cancelling an order"""
    order_id: UUID
    order_number: str
    status: str
    message: str
    refund: RefundInfo


class RefundStatusResponse(BaseModel):
    """Response returned by the refund-status endpoint"""
    order_id: UUID
    order_number: str
    refund_id: Optional[str] = None
    refund_amount: Decimal = Decimal(0)
    restocking_fee: Decimal = Decimal(0)
    fee_percentage: Decimal = Decimal(0)
    # Our stored, user-facing refund phase: refund_initiated | refund_completed | refund_failed
    payment_status: Optional[str] = None
    # Live provider status: processed | pending | failed
    status: str
    message: str