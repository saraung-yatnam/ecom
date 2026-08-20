from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON  # 👈 Add this import
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
    
    # Financials
    subtotal: Decimal = Field(max_digits=12, decimal_places=2)
    discount_total: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    tax_total: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    shipping_total: Decimal = Field(default=0, max_digits=12, decimal_places=2)
    grand_total: Decimal = Field(max_digits=12, decimal_places=2)
    
    # Status
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    payment_status: str = Field(default="pending")
    
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
    # In Order class
    payments: list["Payment"] = Relationship(back_populates="order")


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    order_id: UUID = Field(foreign_key="orders.id", index=True)
    variant_id: UUID = Field(foreign_key="product_variants.id", index=True)
    
    # Snapshot
    product_name: str
    variant_sku: str
    
    # 👇 Fix: Use sa_column=Column(JSON) for dict type
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