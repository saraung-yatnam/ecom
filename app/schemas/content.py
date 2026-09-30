# app/schemas/content.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContentBlockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    title: str
    body: str | None = None
    image_url: str | None = None
    link: str | None = None
    link_label: str | None = None
    sort_order: int = 0
    is_active: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ContentBlockCreate(BaseModel):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9._-]+$")
    title: str = Field(min_length=1, max_length=120)
    body: str | None = Field(default=None, max_length=2000)
    image_url: str | None = Field(default=None, max_length=500)
    link: str | None = Field(default=None, max_length=300)
    link_label: str | None = Field(default=None, max_length=60)
    sort_order: int = Field(default=0, ge=0, le=999)
    is_active: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class ContentBlockUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, max_length=2000)
    image_url: str | None = Field(default=None, max_length=500)
    link: str | None = Field(default=None, max_length=300)
    link_label: str | None = Field(default=None, max_length=60)
    sort_order: int | None = Field(default=None, ge=0, le=999)
    is_active: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class ContentBlockListResponse(BaseModel):
    items: list[ContentBlockRead]
    total: int
    page: int
    limit: int
    total_pages: int


class PublicBlocksResponse(BaseModel):
    """Live blocks grouped by slot — absent slots render hardcoded content."""

    blocks: dict[str, list[ContentBlockRead]]


class ContentImageUploadResponse(BaseModel):
    url: str
    width: int
    height: int
    size_bytes: int
    # Set when the image misses the slot's recommended aspect (warn-only —
    # the upload still succeeds; the storefront crops with object-cover).
    aspect_warning: str | None = None
