from datetime import datetime
from decimal import Decimal
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict


class DiscountTypeEnum(str, Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"


# -------------------------
# Admin Schemas
# -------------------------

class CouponCreate(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    discount_type: DiscountTypeEnum = DiscountTypeEnum.PERCENTAGE
    value: Decimal = Field(gt=0)
    min_order_value: Decimal | None = Field(default=None, gt=0)
    max_uses: int | None = Field(default=None, gt=0)
    max_uses_per_user: int = Field(default=1, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime
    is_active: bool = Field(default=True)


class CouponUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=3, max_length=50)
    discount_type: DiscountTypeEnum | None = None
    value: Decimal | None = Field(default=None, gt=0)
    min_order_value: Decimal | None = Field(default=None, gt=0)
    max_uses: int | None = Field(default=None, gt=0)
    max_uses_per_user: int | None = Field(default=None, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    is_active: bool | None = None


class CouponRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    code: str
    discount_type: str
    value: Decimal
    min_order_value: Decimal | None
    max_uses: int | None
    max_uses_per_user: int
    times_used: int
    valid_from: datetime
    valid_until: datetime
    is_active: bool
    created_by: UUID
    created_at: datetime
    updated_at: datetime


# -------------------------
# Public Schemas
# -------------------------

class CouponValidateRequest(BaseModel):
    code: str


class CouponValidateResponse(BaseModel):
    valid: bool
    message: str
    discount_type: str | None = None
    value: Decimal | None = None
    min_order_value: Decimal | None = None


class ApplyCouponRequest(BaseModel):
    coupon_code: str