from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel


class DiscountType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"


class Coupon(SQLModel, table=True):
    __tablename__ = "coupons"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code: str = Field(unique=True, index=True, max_length=50)
    discount_type: DiscountType = Field(default=DiscountType.PERCENTAGE)
    value: Decimal = Field(max_digits=12, decimal_places=2)
    
    min_order_value: Decimal | None = Field(
        default=None, 
        max_digits=12, 
        decimal_places=2
    )
    max_uses: int | None = None
    max_uses_per_user: int = Field(default=1)
    times_used: int = Field(default=0)
    
    valid_from: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    valid_until: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    is_active: bool = Field(default=True)
    
    created_by: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    
    # Relationships
    creator: "User" = Relationship(back_populates="coupons")