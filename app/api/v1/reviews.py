from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.deps import SessionDep, get_current_user
from app.models.user import User
from app.repositories import review as review_repo
from app.repositories import product as product_repo
from app.repositories import order as order_repo
from app.schemas.review import ReviewCreate, ReviewRead, ReviewUpdate


router = APIRouter(prefix="/reviews", tags=["Reviews"])


@router.post("/{product_id}", response_model=ReviewRead)
def create_review(
    product_id: UUID,
    review_data: ReviewCreate,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Create a review for a product — requires a verified purchase"""
    product = product_repo.get_product_by_id(session, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if review_repo.has_reviewed_product(session, current_user.id, product_id):
        raise HTTPException(
            status_code=400,
            detail="You have already reviewed this product"
        )

    order_id = order_repo.get_verified_purchase_order_id(
        session, current_user.id, product_id
    )
    if not order_id:
        raise HTTPException(
            status_code=403,
            detail="You can only review products you have purchased and received"
        )

    review = review_repo.create_review(
        session,
        product_id,
        current_user.id,
        review_data.model_dump(),
        order_id=order_id,
        is_verified_purchase=True,
    )

    return ReviewRead(
        id=review.id,
        product_id=review.product_id,
        user_id=review.user_id,
        order_id=review.order_id,
        rating=review.rating,
        title=review.title,
        comment=review.comment,
        is_verified_purchase=review.is_verified_purchase,
        created_at=review.created_at,
        updated_at=review.updated_at,
        user_full_name=current_user.full_name
    )


@router.get("/products/{product_id}", response_model=list[ReviewRead])
def get_product_reviews(
    product_id: UUID,
    session: SessionDep,
    skip: int = 0,
    limit: int = 20,
):
    """Get all reviews for a product"""
    product = product_repo.get_product_by_id(session, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return review_repo.get_reviews_by_product(session, product_id, skip, limit)


@router.get("/product/{product_id}/rating", response_model=dict)
def get_product_rating(
    product_id: UUID,
    session: SessionDep,
):
    """Get average rating for a product"""
    product = product_repo.get_product_by_id(session, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    avg_rating = review_repo.get_product_average_rating(session, product_id)
    return {"average_rating": avg_rating}


@router.get("/my-reviews", response_model=list[ReviewRead])
def get_my_reviews(
    session: SessionDep,
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 20,
):
    """Get all reviews by current user"""
    return review_repo.get_reviews_by_user(session, current_user.id, skip, limit)


@router.put("/{review_id}", response_model=ReviewRead)
def update_review(
    review_id: UUID,
    review_data: ReviewUpdate,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Update a review"""
    review = review_repo.get_review_by_id(session, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    review = review_repo.update_review(
        session,
        review,
        review_data.model_dump(exclude_unset=True)
    )

    return ReviewRead(
        id=review.id,
        product_id=review.product_id,
        user_id=review.user_id,
        order_id=review.order_id,
        rating=review.rating,
        title=review.title,
        comment=review.comment,
        is_verified_purchase=review.is_verified_purchase,
        created_at=review.created_at,
        updated_at=review.updated_at,
        user_full_name=current_user.full_name
    )


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(
    review_id: UUID,
    session: SessionDep,
    current_user: User = Depends(get_current_user),
):
    """Delete a review"""
    review = review_repo.get_review_by_id(session, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    review_repo.delete_review(session, review)
    return None