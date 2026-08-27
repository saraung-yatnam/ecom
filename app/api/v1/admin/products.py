from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.api.deps import SessionDep, require_role
from app.models.product import Product
from app.models.user import User, UserRole
from app.repositories import product as product_repo
from app.schemas.product import ProductRead

router = APIRouter(prefix="/admin/products", tags=["Admin Products"])


@router.get("", response_model=dict)
def get_all_products_admin(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = None,
    is_active: bool | None = None,
):
    """
    Get all products with pagination (Admin only).
    """
    skip = (page - 1) * limit
    
    products, total = product_repo.get_all_products_admin(
        session=session,
        skip=skip,
        limit=limit,
        search=search,
        is_active=is_active,
    )
    
    return {
        "products": products,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit,
        }
    }


# 👇 MOVED /export HERE - BEFORE /{product_id}
@router.get("/export", response_model=dict)
def export_products(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
    format: str = Query(default="json"),
):
    """
    Export products data (Admin only).
    """
    # Load products with images and variants
    statement = select(Product).options(
        selectinload(Product.images),
        selectinload(Product.variants)
    )
    products = session.exec(statement).all()
    
    export_data = []
    for product in products:
        export_data.append({
            "id": str(product.id),
            "name": product.name,
            "slug": product.slug,
            "description": product.description,
            "price": str(product.price),
            "compare_at_price": str(product.compare_at_price) if product.compare_at_price else None,
            "is_active": product.is_active,
            "created_at": product.created_at.isoformat(),
            "updated_at": product.updated_at.isoformat(),
            "images": [
                {
                    "id": str(img.id),
                    "url": img.url,
                    "alt_text": img.alt_text,
                    "sort_order": img.sort_order,
                    "created_at": img.created_at.isoformat(),
                }
                for img in product.images
            ],
            "variants": [
                {
                    "id": str(v.id),
                    "product_id": str(v.product_id),
                    "sku": v.sku,
                    "attributes": v.attributes,
                    "price_override": str(v.price_override) if v.price_override else None,
                    "stock": v.stock,
                    "created_at": v.created_at.isoformat(),
                }
                for v in product.variants
            ],
        })
    
    return {
        "format": format,
        "count": len(export_data),
        "data": export_data
    }


# 👇 /{product_id} comes AFTER /export
@router.get("/{product_id}", response_model=ProductRead)
def get_product_admin(
    product_id: UUID,
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.manager, UserRole.admin)),
):
    """
    Get product by ID (Admin only).
    """
    product = product_repo.get_product_by_id(session, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    return product


@router.post("/bulk-delete", response_model=dict)
def bulk_delete_products(
    product_ids: list[UUID],
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """
    Bulk delete products (Admin only).
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
    """
    if not product_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No product IDs provided"
        )
    
    updated_count = product_repo.bulk_update_product_status(session, product_ids, is_active)
    
    return {
        "updated_count": updated_count,
        "message": f"Successfully updated {updated_count} products to {'active' if is_active else 'inactive'}"
    }