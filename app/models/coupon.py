from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel


class Coupon(SQLModel, table=True):
    __tablename__ = "coupons"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code: str = Field(unique=True, index=True)
    discount_type: str = Field(default="percentage")  # percentage, fixed
    value: Decimal = Field(max_digits=12, decimal_places=2)
    
    min_order_value: Decimal | None = None
    max_uses: int | None = None
    max_uses_per_user: int = Field(default=1)
    times_used: int = Field(default=0)
    
    valid_from: datetime
    valid_until: datetime
    is_active: bool = Field(default=True)
    
    created_by: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    # Relationships
    creator: "User" = Relationship(back_populates="coupons")