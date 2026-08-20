import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: str | None = None
    phone: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        if not v.isalnum():
            raise ValueError("Username must be alphanumeric")
        return v


class UserRead(BaseModel):
    id: uuid.UUID
    email: EmailStr
    username: str
    role: UserRole
    full_name: str | None
    is_active: bool
    email_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True  # lets you return an ORM object directly


class UserLogin(BaseModel):
    email: EmailStr
    password: str