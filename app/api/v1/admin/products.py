from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, require_role
from app.models.user import User, UserRole
from app.repositories import product as product_repo

router = APIRouter(prefix="/admin/products", tags=["Admin Products"])


@router.post("/bulk-delete", response_model=dict)
def bulk_delete_products(
    product_ids: list[UUID],
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """
    Bulk delete products (Admin only).
    
    Allowed:
        admin
    """
    if not product_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No product IDs provided"
        )
    
    deleted_count = product_repo.bulk_delete_products(session, product_ids)
    
    return {
        "deleted_count": deleted_count,
        "message": f"Successfully deleted {deleted_count} products"
    }


@router.post("/bulk-update-status", response_model=dict)
def bulk_update_product_status(
    product_ids: list[UUID],
    is_active: bool,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """
    Bulk update product status (Admin only).
    
    Allowed:
        admin
    """
    if not product_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No product IDs provided"
        )
    
    updated_count = product_repo.bulk_update_product_status(session, product_ids, is_active)
    
    return {
        "updated_count": updated_count,
        "message": f"Successfully updated {updated_count} products to { 'active' if is_active else 'inactive' }"
    }


@router.get("/export", response_model=dict)
def export_products(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
    format: str = "json",
):
    """
    Export products data (Admin only).
    
    Allowed:
        admin
    """
    products = product_repo.get_all_products(session)
    
    # Convert to export format
    export_data = []
    for product in products:
        export_data.append({
            "id": str(product.id),
            "name": product.name,
            "slug": product.slug,
            "price": str(product.price),
            "is_active": product.is_active,
            "created_at": product.created_at.isoformat(),
        })
    
    return {
        "format": format,
        "count": len(export_data),
        "data": export_data
    }