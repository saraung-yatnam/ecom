# app/models/order.py
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel


class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class Order(SQLModel, table=True):
    __tablename__ = "orders"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    order_number: str = Field(unique=True, index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    
    # Addresses
    shipping_address_id: UUID = Field(foreign_key="addresses.id")
    billing_address_id: UUID = Field(foreign_key="addresses.id")
    
    # 👇 ADD THESE TWO RELATIONSHIPS
    shipping_address: "Address" = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Order.shipping_address_id]",
            "primaryjoin": "Order.shipping_address_id == Address.id",
        }
    )
    billing_address: "Address" = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[Order.billing_address_id]",
            "primaryjoin": "Order.billing_address_id == Address.id",
        }
    )
    
    # Financials
    subtotal: Decimal = Field(max_digits=12, decimal_places=2)
    discount_total: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    tax_total: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    shipping_total: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    grand_total: Decimal = Field(max_digits=12, decimal_places=2)
    
    # Coupon
    coupon_code: str | None = None
    
    # Coupon
    coupon_code: str | None = None
    
    # Payment
    payment_method: str | None = None  # 'cod' or 'online' (choice made at checkout)
    cod_fee: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    
    # Status
    # Status
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    payment_status: str = Field(default="pending")

    # Cancellation
    cancellation_reason: str | None = None
    cancelled_at: datetime | None = None

    # Refund
    refund_amount: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    refund_id: str | None = None           # Razorpay refund ID (rfnd_xxx)
    refund_reason: str | None = None
    restocking_fee: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    refunded_at: datetime | None = None

    # Timestamps
    placed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None

    # Relationships - use string references to avoid circular imports
    user: "User" = Relationship(back_populates="orders")
    items: list["OrderItem"] = Relationship(back_populates="order")
    payments: list["Payment"] = Relationship(back_populates="order")
    reviews: list["Review"] = Relationship(back_populates="order")

    # ---------------------------------------------------------
    # Computed helpers (not DB columns)
    # ---------------------------------------------------------
    @property
    def succeeded_payment(self):
        """The payment that captured money for this order (None if never paid).

        Matches `succeeded` and `refunded` payments — a refunded payment was
        still a real transaction, so it keeps an identifiable transaction ID.
        """
        for payment in self.payments or []:
            status = getattr(payment, "status", None)
            value = getattr(status, "value", status)
            if value in ("succeeded", "refunded"):
                return payment
        return None

    @property
    def transaction_id(self) -> str | None:
        """Razorpay transaction ID (pay_xxx) for a paid order.

        Resolves from the succeeded payment record: prefers the provider
        payment intent (pay_xxx) and falls back to the provider payment /
        order ID (order_xxx, or dummy_pay_xxx in dev).
        """
        payment = self.succeeded_payment
        if payment is None:
            return None
        return payment.provider_payment_intent or payment.provider_payment_id

    @property
    def can_cancel(self) -> bool:
        """Orders can be cancelled while PENDING, CONFIRMED or PROCESSING."""
        return self.status in (
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
        )

    @property
    def can_refund(self) -> bool:
        """Refund is possible only for paid online orders not fully refunded."""
        if self.payment_method == "cod" or self.payment_status != "paid":
            return False
        already_refunded = self.refund_amount or Decimal(0)
        return already_refunded < self.grand_total

    @property
    def restocking_fee_percentage(self) -> float:
        """Restocking fee % based on the order status at cancellation time."""
        from app.core.config import settings

        if self.status == OrderStatus.PROCESSING:
            return settings.RESTOCKING_FEE_PROCESSING
        if self.status == OrderStatus.CONFIRMED:
            return settings.RESTOCKING_FEE_CONFIRMED
        return settings.RESTOCKING_FEE_PENDING


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    order_id: UUID = Field(foreign_key="orders.id", index=True)
    variant_id: UUID = Field(foreign_key="product_variants.id", index=True)
    
    # Snapshot
    product_name: str
    variant_sku: str
    
    # Use sa_column=Column(JSON) for dict type
    variant_attributes: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False)
    )
    
    quantity: int
    unit_price: Decimal = Field(max_digits=12, decimal_places=2)
    line_total: Decimal = Field(max_digits=12, decimal_places=2)
    
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    # Relationships - use string references
    order: "Order" = Relationship(back_populates="items")
    variant: "ProductVariant" = Relationship(back_populates="order_items")