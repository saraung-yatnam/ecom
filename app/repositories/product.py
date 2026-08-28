from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlmodel import Session

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
            selectinload(Product.images)
        )
    )

    if search:
        statement = statement.where(
            Product.name.ilike(f"%{search}%")
        )

    if category_id:
        statement = statement.where(
            Product.category_id == category_id
        )

    if min_price is not None:
        statement = statement.where(
            Product.price >= min_price
        )

    if max_price is not None:
        statement = statement.where(
            Product.price <= max_price
        )

    if sort == "price_asc":
        statement = statement.order_by(Product.price.asc())
    elif sort == "price_desc":
        statement = statement.order_by(Product.price.desc())
    elif sort == "name_asc":
        statement = statement.order_by(Product.name.asc())
    elif sort == "name_desc":
        statement = statement.order_by(Product.name.desc())
    elif sort == "oldest":
        statement = statement.order_by(Product.created_at.asc())
    else:
        statement = statement.order_by(Product.created_at.desc())

    statement = statement.offset(skip).limit(limit)

    result = session.execute(statement)
    return result.scalars().all()


def get_product_by_id(
    session: Session,
    product_id: UUID,
) -> Product | None:

    statement = (
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.variants),
            selectinload(Product.images)
        )
    )

    result = session.execute(statement)
    return result.scalar_one_or_none()


def get_product_by_slug(
    session: Session,
    slug: str,
) -> Product | None:

    statement = (
        select(Product)
        .where(Product.slug == slug)
        .options(
            selectinload(Product.variants),
            selectinload(Product.images)
        )
    )

    result = session.execute(statement)
    return result.scalar_one_or_none()


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

    result = session.execute(statement)
    return result.scalars().all()


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

    result = session.execute(statement)
    return result.scalar_one_or_none()


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


# =========================================================
# VARIANTS - DELETE  ⬅️ NEW FUNCTION
# =========================================================

def delete_variant(
    session: Session,
    variant: ProductVariant,
) -> None:
    """
    Delete a product variant (hard delete).
    """
    session.delete(variant)
    session.commit()


# =========================================================
# ADMIN FUNCTIONS
# =========================================================

def get_total_products(session: Session) -> int:
    """Get total number of products"""
    statement = select(func.count(Product.id))
    result = session.execute(statement)
    return result.scalar() or 0


def get_all_products(session: Session) -> list[Product]:
    """Get all products (for export)"""
    statement = select(Product).options(
        selectinload(Product.images),
        selectinload(Product.variants)
    ).order_by(Product.created_at.desc())
    result = session.execute(statement)
    return result.scalars().all()


def get_all_products_admin(
    session: Session,
    skip: int = 0,
    limit: int = 20,
    search: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[Product], int]:
    """
    Get all products with filters (Admin only).
    Includes inactive products.
    """
    statement = select(Product).options(
        selectinload(Product.variants),
        selectinload(Product.images)
    )
    
    if search:
        statement = statement.where(
            (Product.name.ilike(f"%{search}%")) |
            (Product.slug.ilike(f"%{search}%"))
        )
    
    if is_active is not None:
        statement = statement.where(Product.is_active == is_active)
    
    # Get total count
    count_statement = select(func.count()).select_from(statement.subquery())
    result = session.execute(count_statement)
    total = result.scalar() or 0
    
    statement = statement.order_by(Product.created_at.desc()).offset(skip).limit(limit)
    result = session.execute(statement)
    products = result.scalars().all()
    
    return products, total


def bulk_delete_products(session: Session, product_ids: list[UUID]) -> int:
    """Bulk delete products"""
    if not product_ids:
        return 0
    
    statement = select(Product).where(Product.id.in_(product_ids))
    result = session.execute(statement)
    products = result.scalars().all()
    
    count = len(products)
    for product in products:
        session.delete(product)
    
    session.commit()
    return count


def bulk_update_product_status(session: Session, product_ids: list[UUID], is_active: bool) -> int:
    """Bulk update product status"""
    if not product_ids:
        return 0
    
    statement = select(Product).where(Product.id.in_(product_ids))
    result = session.execute(statement)
    products = result.scalars().all()
    
    count = len(products)
    for product in products:
        product.is_active = is_active
    
    session.commit()
    return count


def get_products_for_export(session: Session) -> list[dict]:
    """Get products in export format"""
    products = get_all_products(session)
    
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
                }
                for img in product.images
            ],
            "variants": [
                {
                    "id": str(v.id),
                    "sku": v.sku,
                    "attributes": v.attributes,
                    "price_override": str(v.price_override) if v.price_override else None,
                    "stock": v.stock,
                }
                for v in product.variants
            ],
        })
    
    return export_data


# =========================================================
# VARIANT HELPER FUNCTIONS
# =========================================================

def get_variant_by_product_and_sku(
    session: Session,
    product_id: UUID,
    sku: str,
) -> ProductVariant | None:
    """Get a variant by product ID and SKU"""
    statement = select(ProductVariant).where(
        ProductVariant.product_id == product_id,
        ProductVariant.sku == sku
    )
    result = session.execute(statement)
    return result.scalar_one_or_none()


def get_variants_by_product_ids(
    session: Session,
    product_ids: list[UUID],
) -> dict[UUID, list[ProductVariant]]:
    """Get variants for multiple products at once"""
    if not product_ids:
        return {}
    
    statement = select(ProductVariant).where(
        ProductVariant.product_id.in_(product_ids)
    )
    result = session.execute(statement)
    variants = result.scalars().all()
    
    # Group by product_id
    variants_by_product = {}
    for variant in variants:
        if variant.product_id not in variants_by_product:
            variants_by_product[variant.product_id] = []
        variants_by_product[variant.product_id].append(variant)
    
    return variants_by_product