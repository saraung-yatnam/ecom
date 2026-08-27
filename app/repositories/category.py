from uuid import UUID

from sqlalchemy import select
from sqlmodel import Session

from app.models.category import Category
from app.schemas.category import CategoryCreate, CategoryUpdate


def get_categories(session: Session, skip: int = 0, limit: int = 100) -> list[Category]:
    statement = select(Category).order_by(Category.name.asc()).offset(skip).limit(limit)
    result = session.execute(statement)
    return result.scalars().all()


def get_category_by_id(session: Session, category_id: UUID) -> Category | None:
    return session.get(Category, category_id)


def get_category_by_slug(session: Session, slug: str) -> Category | None:
    statement = select(Category).where(Category.slug == slug)
    result = session.execute(statement)
    return result.scalar_one_or_none()


def create_category(session: Session, category_data: CategoryCreate) -> Category:
    category = Category(**category_data.model_dump())
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def update_category(session: Session, category: Category, category_data: CategoryUpdate) -> Category:
    update_data = category_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(category, field, value)

    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def delete_category(session: Session, category: Category) -> None:
    session.delete(category)
    session.commit()
