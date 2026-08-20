from uuid import UUID

from sqlalchemy import select, func
from sqlmodel import Session

from app.models.review import Review
from app.models.user import User
from app.schemas.review import ReviewRead  # 👈 Add this import


def create_review(
    session: Session,
    product_id: UUID,
    user_id: UUID,
    review_data: dict,
    order_id: UUID | None = None,
) -> Review:
    """Create a new review"""
    review = Review(
        product_id=product_id,
        user_id=user_id,
        order_id=order_id,
        **review_data
    )
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def get_reviews_by_product(
    session: Session,
    product_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> list[ReviewRead]:  # 👈 Change return type to ReviewRead
    """Get all reviews for a product with user info"""
    statement = (
        select(Review, User.full_name)
        .join(User, Review.user_id == User.id)
        .where(Review.product_id == product_id)
        .order_by(Review.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = session.execute(statement)
    
    reviews = []
    for review, full_name in result:
        # 👇 Create ReviewRead object with user_full_name
        review_data = ReviewRead(
            id=review.id,
            product_id=review.product_id,
            user_id=review.user_id,
            order_id=review.order_id,
            rating=review.rating,
            title=review.title,
            comment=review.comment,
            created_at=review.created_at,
            updated_at=review.updated_at,
            user_full_name=full_name  # 👈 Set the user's full name
        )
        reviews.append(review_data)
    
    return reviews


def get_review_by_id(session: Session, review_id: UUID) -> Review | None:
    """Get a review by ID"""
    return session.get(Review, review_id)


def get_reviews_by_user(
    session: Session,
    user_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> list[Review]:
    """Get all reviews by a user with user info"""
    statement = (
        select(Review, User.full_name)
        .join(User, Review.user_id == User.id)
        .where(Review.user_id == user_id)
        .order_by(Review.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = session.execute(statement)
    
    reviews = []
    for review, full_name in result:
        review_data = ReviewRead(
            id=review.id,
            product_id=review.product_id,
            user_id=review.user_id,
            order_id=review.order_id,
            rating=review.rating,
            title=review.title,
            comment=review.comment,
            created_at=review.created_at,
            updated_at=review.updated_at,
            user_full_name=full_name
        )
        reviews.append(review_data)
    
    return reviews


def get_product_average_rating(
    session: Session,
    product_id: UUID,
) -> float:
    """Get average rating for a product"""
    statement = select(func.avg(Review.rating)).where(
        Review.product_id == product_id
    )
    result = session.execute(statement)
    return round(result.scalar() or 0, 1)


def update_review(
    session: Session,
    review: Review,
    review_data: dict,
) -> Review:
    """Update a review"""
    for key, value in review_data.items():
        if value is not None:
            setattr(review, key, value)
    
    session.add(review)
    session.commit()
    session.refresh(review)
    return review


def delete_review(session: Session, review: Review) -> None:
    """Delete a review"""
    session.delete(review)
    session.commit()