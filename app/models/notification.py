# app/models/notification.py
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class NotificationType(str, Enum):
    ORDER_PLACED = "order_placed"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_STATUS = "order_status"
    PROMOTION = "promotion"


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)

    type: NotificationType = Field(index=True)
    title: str
    message: str | None = None
    link: str | None = None
    order_id: UUID | None = Field(default=None, index=True)

    # 👇 Groups every row created by one promotional broadcast (history view)
    broadcast_id: UUID | None = Field(default=None, index=True)

    is_read: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )