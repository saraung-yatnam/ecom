from uuid import UUID

from fastapi import APIRouter, Depends, Request, HTTPException, status

from app.api.deps import SessionDep, require_perm
from app.repositories import audit as audit_repo
from app.models.user import User
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
    request: Request,
    current_user: User = Depends(require_perm("categories.manage")),
):
    """Create a category."""
    existing = category_repo.get_category_by_slug(session, category_data.slug)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category slug already exists")

    category = category_repo.create_category(session, category_data)
    audit_repo.log_and_commit(
        session, action="category.created", entity="category",
        entity_id=category.id, actor_id=current_user.id,
        after={"name": category.name, "slug": category.slug},
        ip_address=audit_repo.client_ip(request),
    )
    return category


@router.put("/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: UUID,
    category_data: CategoryUpdate,
    session: SessionDep,
    request: Request,
    current_user: User = Depends(require_perm("categories.manage")),
):
    """Update a category."""
    category = category_repo.get_category_by_id(session, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    if category_data.slug and category_data.slug != category.slug:
        existing = category_repo.get_category_by_slug(session, category_data.slug)
        if existing and existing.id != category.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category slug already exists")

    before = {"name": category.name, "slug": category.slug}
    updated = category_repo.update_category(session, category, category_data)
    audit_repo.log_and_commit(
        session, action="category.updated", entity="category",
        entity_id=category.id, actor_id=current_user.id,
        before=before,
        after={"name": updated.name, "slug": updated.slug},
        ip_address=audit_repo.client_ip(request),
    )
    return updated


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: UUID,
    session: SessionDep,
    request: Request,
    current_user: User = Depends(require_perm("categories.manage")),
):
    """Delete a category."""
    category = category_repo.get_category_by_id(session, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    snapshot = {"name": category.name, "slug": category.slug}
    category_repo.delete_category(session, category)
    audit_repo.log_and_commit(
        session, action="category.deleted", entity="category",
        entity_id=category_id, actor_id=current_user.id,
        before=snapshot,
        ip_address=audit_repo.client_ip(request),
    )
    return None
