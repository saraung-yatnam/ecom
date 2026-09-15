# app/schemas/notification.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    title: str
    message: str | None
    link: str | None
    order_id: UUID | None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationRead]
    total: int
    unread_count: int


class UnreadCountResponse(BaseModel):
    count: int


class MarkAllReadResponse(BaseModel):
    updated: int


class DeleteResponse(BaseModel):
    ok: bool


class PromotionBroadcastRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    link: str | None = Field(default=None, max_length=300)


class PromotionBroadcastResponse(BaseModel):
    broadcast_id: UUID
    title: str
    message: str
    link: str | None
    recipients_count: int
    created_at: datetime


class PromotionHistoryItem(BaseModel):
    id: UUID
    title: str
    message: str | None
    link: str | None
    recipients_count: int
    created_at: datetime


class PromotionRetractResponse(BaseModel):
    deleted_count: int