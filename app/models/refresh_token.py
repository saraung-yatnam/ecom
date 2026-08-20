from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime
from sqlmodel import SQLModel, Field


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True
    )

    user_id: uuid.UUID = Field(
        foreign_key="users.id",
        index=True
    )

    token_hash: str = Field(
        unique=True,
        index=True
    )

    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )

    revoked: bool = Field(default=False)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )