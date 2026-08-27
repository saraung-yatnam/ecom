from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel


class Category(SQLModel, table=True):
    __tablename__ = "categories"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
    )

    name: str = Field(
        min_length=1,
        max_length=100,
        index=True,
    )

    slug: str = Field(
        min_length=1,
        max_length=120,
        unique=True,
        index=True,
    )

    parent_id: UUID | None = Field(
        default=None,
        foreign_key="categories.id",
        index=True,
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    products: list["Product"] = Relationship(
        back_populates="category"
    )