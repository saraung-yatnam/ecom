from datetime import datetime, timezone
from enum import Enum
import uuid

from sqlmodel import SQLModel, Field, Relationship  # 👈 Add Relationship here


class UserRole(str, Enum):
    customer = "customer"
    staff = "staff"
    manager = "manager"
    admin = "admin"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, nullable=False)
    username: str = Field(unique=True, index=True, nullable=False)
    password_hash: str
    role: UserRole = Field(default=UserRole.customer, index=True)
    full_name: str | None = None
    phone: str | None = None
    is_active: bool = Field(default=True)
    email_verified: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    # 👇 Relationship to cart (ONE user has ONE cart)
    cart: "Cart" = Relationship(
        back_populates="user", 
        sa_relationship_kwargs={"uselist": False}
    )
    # In app/models/user.py
    addresses: list["Address"] = Relationship(back_populates="user")
    orders: list["Order"] = Relationship(back_populates="user")