from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, require_perm
from app.repositories import product_image as image_repo
from app.repositories import product as product_repo
from app.models.user import User
from app.schemas.product_image import (
    ProductImageCreate,
    ProductImageRead,
    ProductImageUpdate,
)

router = APIRouter(
    prefix="/products/{product_id}/images",
    tags=["Product Images"],
)


@router.get("", response_model=list[ProductImageRead])
def get_images(
    product_id: UUID,
    session: SessionDep,
):
    """Get all images for a product"""
    
    product = product_repo.get_product_by_id(session, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    return image_repo.get_product_images(session, product_id)


@router.post("", response_model=ProductImageRead, status_code=status.HTTP_201_CREATED)
def add_image(
    product_id: UUID,
    image_data: ProductImageCreate,
    session: SessionDep,
    current_user: User = Depends(
        require_perm("product_images.manage")
    ),
):
    """Add an image to a product"""
    
    product = product_repo.get_product_by_id(session, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    try:
        return image_repo.create_product_image(session, product_id, image_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{image_id}", response_model=ProductImageRead)
def update_image(
    product_id: UUID,
    image_id: UUID,
    image_data: ProductImageUpdate,
    session: SessionDep,
    current_user: User = Depends(
        require_perm("product_images.manage")
    ),
):
    """Update an image"""
    
    image = image_repo.get_image_by_id(session, image_id)
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    if image.product_id != product_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image does not belong to this product"
        )
    
    return image_repo.update_product_image(session, image, image_data)


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(
    product_id: UUID,
    image_id: UUID,
    session: SessionDep,
    current_user: User = Depends(
        require_perm("product_images.manage")
    ),
):
    """Delete an image"""
    
    image = image_repo.get_image_by_id(session, image_id)
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found"
        )
    
    if image.product_id != product_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image does not belong to this product"
        )
    
    image_repo.delete_product_image(session, image)


@router.post("/reorder", response_model=list[ProductImageRead])
def reorder_images(
    product_id: UUID,
    image_ids: list[UUID],
    session: SessionDep,
    current_user: User = Depends(
        require_perm("product_images.manage")
    ),
):
    """Reorder images for a product"""
    
    product = product_repo.get_product_by_id(session, product_id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )
    
    return image_repo.reorder_product_images(session, product_id, image_ids)