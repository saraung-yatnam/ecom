from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import SessionDep, require_role
from app.models.user import User, UserRole
from app.repositories import category as category_repo
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get("", response_model=list[CategoryRead])
def get_categories(
    session: SessionDep,
    skip: int = 0,
    limit: int = 100,
):
    """Get all categories."""
    return category_repo.get_categories(session, skip=skip, limit=limit)


@router.get("/{category_id}", response_model=CategoryRead)
def get_category(
    category_id: UUID,
    session: SessionDep,
):
    """Get a category by ID."""
    category = category_repo.get_category_by_id(session, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    category_data: CategoryCreate,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """Create a category."""
    existing = category_repo.get_category_by_slug(session, category_data.slug)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category slug already exists")

    return category_repo.create_category(session, category_data)


@router.put("/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: UUID,
    category_data: CategoryUpdate,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """Update a category."""
    category = category_repo.get_category_by_id(session, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    if category_data.slug and category_data.slug != category.slug:
        existing = category_repo.get_category_by_slug(session, category_data.slug)
        if existing and existing.id != category.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category slug already exists")

    return category_repo.update_category(session, category, category_data)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """Delete a category."""
    category = category_repo.get_category_by_id(session, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    category_repo.delete_category(session, category)
    return None
