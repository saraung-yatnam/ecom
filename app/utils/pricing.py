from decimal import Decimal
from typing import Union

from app.models.product import Product, ProductVariant


def get_effective_price(
    product: Product,
    variant: ProductVariant | None = None
) -> Decimal:
    """
    Get the effective price for a product/variant.
    
    Args:
        product: The product object
        variant: Optional variant object
    
    Returns:
        Decimal: Effective price
    """
    if variant and variant.price_override:
        return variant.price_override
    return product.price


def get_discount_percentage(
    product: Product,
    variant: ProductVariant | None = None
) -> int:
    """
    Calculate discount percentage.
    
    Args:
        product: The product object
        variant: Optional variant object
    
    Returns:
        int: Discount percentage (0-100)
    """
    price = get_effective_price(product, variant)
    
    if product.compare_at_price and product.compare_at_price > price:
        discount = product.compare_at_price - price
        percentage = (discount / product.compare_at_price) * 100
        return round(percentage)
    return 0


def get_savings_amount(
    product: Product,
    variant: ProductVariant | None = None
) -> Decimal:
    """
    Calculate total savings amount.
    
    Args:
        product: The product object
        variant: Optional variant object
    
    Returns:
        Decimal: Savings amount
    """
    price = get_effective_price(product, variant)
    
    if product.compare_at_price and product.compare_at_price > price:
        return product.compare_at_price - price
    return Decimal("0.00")


def get_variant_price_with_currency(
    product: Product,
    variant: ProductVariant,
    currency_symbol: str = "₹"
) -> str:
    """
    Get formatted variant price with currency.
    
    Args:
        product: The product object
        variant: The variant object
        currency_symbol: Currency symbol (default: ₹)
    
    Returns:
        str: Formatted price (e.g., "₹749.00")
    """
    price = get_effective_price(product, variant)
    return f"{currency_symbol}{price:.2f}"


def get_discount_badge_text(
    product: Product,
    variant: ProductVariant | None = None
) -> str | None:
    """
    Generate discount badge text.
    
    Args:
        product: The product object
        variant: Optional variant object
    
    Returns:
        str | None: Discount text or None if no discount
    """
    percentage = get_discount_percentage(product, variant)
    if percentage > 0:
        return f"Save {percentage}%"
    return None


def get_product_pricing_data(
    product: Product
) -> dict:
    """
    Get complete pricing data for a product.
    
    Args:
        product: The product object
    
    Returns:
        dict: Complete pricing information
    """
    return {
        "price": product.price,
        "compare_at_price": product.compare_at_price,
        "discount_percentage": get_discount_percentage(product),
        "savings_amount": get_savings_amount(product),
        "is_on_sale": product.compare_at_price is not None and 
                     product.compare_at_price > product.price
    }


def get_variant_pricing_data(
    product: Product,
    variant: ProductVariant
) -> dict:
    """
    Get complete pricing data for a variant.
    
    Args:
        product: The product object
        variant: The variant object
    
    Returns:
        dict: Complete pricing information for the variant
    """
    effective_price = get_effective_price(product, variant)
    
    return {
        "price": product.price,
        "compare_at_price": product.compare_at_price,
        "effective_price": effective_price,
        "price_override": variant.price_override,
        "discount_percentage": get_discount_percentage(product, variant),
        "savings_amount": get_savings_amount(product, variant),
        "is_on_sale": product.compare_at_price is not None and 
                     product.compare_at_price > effective_price
    }