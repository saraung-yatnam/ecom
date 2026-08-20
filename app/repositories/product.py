from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.product import Product, ProductVariant
from app.schemas.product import (
    ProductCreate,
    ProductUpdate,
    ProductVariantCreate,
    ProductVariantUpdate,
)


def get_products(
    session: Session,
    search: str | None = None,
    category_id: UUID | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    sort: str = "newest",
    skip: int = 0,
    limit: int = 20,
) -> list[Product]:

    statement = (
        select(Product)
        .where(Product.is_active == True)
        .options(
            selectinload(Product.variants),
            selectinload(Product.images)  # 👈 Added images
        )
    )

    # ---------------------------------------------
    # SEARCH
    # ---------------------------------------------

    if search:
        statement = statement.where(
            Product.name.ilike(f"%{search}%")
        )

    # ---------------------------------------------
    # CATEGORY FILTER
    # ---------------------------------------------

    if category_id:
        statement = statement.where(
            Product.category_id == category_id
        )

    # ---------------------------------------------
    # PRICE FILTERS
    # ---------------------------------------------

    if min_price is not None:
        statement = statement.where(
            Product.price >= min_price
        )

    if max_price is not None:
        statement = statement.where(
            Product.price <= max_price
        )

    # ---------------------------------------------
    # SORTING
    # ---------------------------------------------

    if sort == "price_asc":

        statement = statement.order_by(
            Product.price.asc()
        )

    elif sort == "price_desc":

        statement = statement.order_by(
            Product.price.desc()
        )

    elif sort == "name_asc":

        statement = statement.order_by(
            Product.name.asc()
        )

    elif sort == "name_desc":

        statement = statement.order_by(
            Product.name.desc()
        )

    elif sort == "oldest":

        statement = statement.order_by(
            Product.created_at.asc()
        )

    else:
        # newest
        statement = statement.order_by(
            Product.created_at.desc()
        )

    # ---------------------------------------------
    # PAGINATION
    # ---------------------------------------------

    statement = statement.offset(skip).limit(limit)

    return session.exec(statement).all()


def get_product_by_id(
    session: Session,
    product_id: UUID,
) -> Product | None:

    statement = (
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.variants),
            selectinload(Product.images)  # 👈 Added images
        )
    )

    return session.exec(statement).first()


def get_product_by_slug(
    session: Session,
    slug: str,
) -> Product | None:

    statement = (
        select(Product)
        .where(Product.slug == slug)
        .options(
            selectinload(Product.variants),
            selectinload(Product.images)  # 👈 Added images
        )
    )

    return session.exec(statement).first()


def create_product(
    session: Session,
    product_data: ProductCreate,
    created_by: UUID,
) -> Product:

    product = Product(
        **product_data.model_dump(),
        created_by=created_by,
    )

    session.add(product)
    session.commit()
    session.refresh(product)

    return product


def update_product(
    session: Session,
    product: Product,
    product_data: ProductUpdate,
) -> Product:

    update_data = product_data.model_dump(
        exclude_unset=True
    )

    for field, value in update_data.items():
        setattr(
            product,
            field,
            value,
        )

    session.add(product)
    session.commit()
    session.refresh(product)

    return product


def delete_product(
    session: Session,
    product: Product,
) -> None:

    # Soft delete.
    product.is_active = False

    session.add(product)
    session.commit()


# =========================================================
# VARIANTS
# =========================================================

def get_variants(
    session: Session,
    product_id: UUID,
) -> list[ProductVariant]:

    statement = select(ProductVariant).where(
        ProductVariant.product_id == product_id
    )

    return session.exec(statement).all()


def get_variant_by_id(
    session: Session,
    variant_id: UUID,
) -> ProductVariant | None:

    return session.get(
        ProductVariant,
        variant_id,
    )


def get_variant_by_sku(
    session: Session,
    sku: str,
) -> ProductVariant | None:

    statement = select(ProductVariant).where(
        ProductVariant.sku == sku
    )

    return session.exec(statement).first()


def create_variant(
    session: Session,
    product_id: UUID,
    variant_data: ProductVariantCreate,
) -> ProductVariant:

    variant = ProductVariant(
        product_id=product_id,
        **variant_data.model_dump(),
    )

    session.add(variant)
    session.commit()
    session.refresh(variant)

    return variant


def update_variant(
    session: Session,
    variant: ProductVariant,
    variant_data: ProductVariantUpdate,
) -> ProductVariant:

    update_data = variant_data.model_dump(
        exclude_unset=True
    )

    for field, value in update_data.items():
        setattr(
            variant,
            field,
            value,
        )

    session.add(variant)
    session.commit()
    session.refresh(variant)

    return variant