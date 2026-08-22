from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, extract
from sqlmodel import Session, select

from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User


def get_sales_report(
    session: Session,
    from_date: date,
    to_date: date,
    group_by: str = "day",
) -> dict:
    """
    Get sales report grouped by day, week, or month.
    """
    # Base query
    statement = select(
        func.sum(Order.grand_total).label("total_sales"),
        func.count(Order.id).label("order_count"),
        func.avg(Order.grand_total).label("average_order_value"),
    ).where(
        Order.placed_at >= from_date,
        Order.placed_at <= to_date,
        Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED, OrderStatus.SHIPPED]),
    )
    
    result = session.exec(statement).first()
    
    # Group by period
    if group_by == "day":
        group_col = func.date(Order.placed_at)
    elif group_by == "week":
        group_col = func.date_trunc('week', Order.placed_at)
    elif group_by == "month":
        group_col = func.date_trunc('month', Order.placed_at)
    else:
        group_col = func.date(Order.placed_at)
    
    statement = select(
        group_col.label("period"),
        func.sum(Order.grand_total).label("total_sales"),
        func.count(Order.id).label("order_count"),
        func.avg(Order.grand_total).label("average_order_value"),
    ).where(
        Order.placed_at >= from_date,
        Order.placed_at <= to_date,
        Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED, OrderStatus.SHIPPED]),
    ).group_by(group_col).order_by(group_col)
    
    period_data = session.exec(statement).all()
    
    return {
        "summary": {
            "total_sales": float(result[0] or 0),
            "order_count": result[1] or 0,
            "average_order_value": float(result[2] or 0),
        },
        "period_data": [
            {
                "period": str(row[0]),
                "total_sales": float(row[1] or 0),
                "order_count": row[2] or 0,
                "average_order_value": float(row[3] or 0),
            }
            for row in period_data
        ]
    }


def get_top_products(
    session: Session,
    limit: int = 10,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict]:
    """
    Get top selling products.
    """
    statement = (
        select(
            Product.id,
            Product.name,
            Product.slug,
            func.sum(OrderItem.quantity).label("total_quantity_sold"),
            func.sum(OrderItem.line_total).label("total_revenue"),
            func.avg(OrderItem.unit_price).label("average_price"),
        )
        .join(OrderItem, Product.id == OrderItem.variant_id)
        .join(Order, OrderItem.order_id == Order.id)
    )
    
    if from_date:
        statement = statement.where(Order.placed_at >= from_date)
    if to_date:
        statement = statement.where(Order.placed_at <= to_date)
    
    statement = statement.where(
        Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED, OrderStatus.SHIPPED])
    ).group_by(Product.id, Product.name, Product.slug)
    
    statement = statement.order_by(func.sum(OrderItem.quantity).desc()).limit(limit)
    
    results = session.exec(statement).all()
    
    return [
        {
            "product_id": str(row[0]),
            "product_name": row[1],
            "product_slug": row[2],
            "total_quantity_sold": row[3] or 0,
            "total_revenue": float(row[4] or 0),
            "average_price": float(row[5] or 0),
        }
        for row in results
    ]


def get_order_statistics(
    session: Session,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict:
    """
    Get order statistics by status.
    """
    status_counts = {}
    total_revenue_by_status = {}
    
    for status in OrderStatus:
        statement = select(
            func.count(Order.id),
            func.sum(Order.grand_total),
        ).where(Order.status == status)
        
        if from_date:
            statement = statement.where(Order.placed_at >= from_date)
        if to_date:
            statement = statement.where(Order.placed_at <= to_date)
        
        result = session.exec(statement).first()
        status_counts[status.value] = result[0] or 0
        total_revenue_by_status[status.value] = float(result[1] or 0)
    
    # Total orders
    total_statement = select(func.count(Order.id)).where(
        Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED, OrderStatus.SHIPPED])
    )
    if from_date:
        total_statement = total_statement.where(Order.placed_at >= from_date)
    if to_date:
        total_statement = total_statement.where(Order.placed_at <= to_date)
    total_orders = session.exec(total_statement).first() or 0
    
    return {
        "total_orders": total_orders,
        "by_status": [
            {
                "status": status,
                "count": status_counts.get(status, 0),
                "revenue": total_revenue_by_status.get(status, 0),
            }
            for status in status_counts.keys()
        ]
    }


def get_revenue_report(
    session: Session,
    from_date: date,
    to_date: date,
    group_by: str = "day",
) -> dict:
    """
    Get revenue report.
    """
    # 👇 FIX: Define group_col based on group_by
    if group_by == "day":
        group_col = func.date(Order.placed_at)
    elif group_by == "week":
        group_col = func.date_trunc('week', Order.placed_at)
    elif group_by == "month":
        group_col = func.date_trunc('month', Order.placed_at)
    else:
        group_col = func.date(Order.placed_at)
    
    statement = select(
        group_col.label("period"),
        func.sum(Order.grand_total).label("revenue"),
        func.sum(Order.discount_total).label("discounts"),
        func.sum(Order.tax_total).label("tax"),
        func.sum(Order.shipping_total).label("shipping"),
    ).where(
        Order.placed_at >= from_date,
        Order.placed_at <= to_date,
        Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED, OrderStatus.SHIPPED]),
    ).group_by(group_col).order_by(group_col)
    
    results = session.exec(statement).all()
    
    return {
        "period_data": [
            {
                "period": str(row[0]),
                "revenue": float(row[1] or 0),
                "discounts": float(row[2] or 0),
                "tax": float(row[3] or 0),
                "shipping": float(row[4] or 0),
                "net_revenue": float((row[1] or 0) - (row[2] or 0)),
            }
            for row in results
        ]
    }


def get_customer_summary(
    session: Session,
    from_date: date | None = None,
    to_date: date | None = None,
) -> dict:
    """
    Get customer analytics summary.
    """
    # Total customers
    total_customers = session.exec(select(func.count(User.id))).first() or 0
    
    # Active customers (placed order in period)
    statement = select(func.count(User.id.distinct())).select_from(Order).join(
        User, Order.user_id == User.id
    )
    if from_date:
        statement = statement.where(Order.placed_at >= from_date)
    if to_date:
        statement = statement.where(Order.placed_at <= to_date)
    
    active_customers = session.exec(statement).first() or 0
    
    # New customers (registered in period)
    statement = select(func.count(User.id))
    if from_date:
        statement = statement.where(User.created_at >= from_date)
    if to_date:
        statement = statement.where(User.created_at <= to_date)
    new_customers = session.exec(statement).first() or 0
    
    # Repeat customers
    if from_date and to_date:
        statement = select(
            User.id,
            func.count(Order.id).label("order_count"),
        ).join(Order, User.id == Order.user_id).where(
            Order.placed_at >= from_date,
            Order.placed_at <= to_date,
            Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED]),
        ).group_by(User.id).having(func.count(Order.id) > 1)
        
        repeat_customers = len(session.exec(statement).all())
    else:
        repeat_customers = 0
    
    return {
        "total_customers": total_customers,
        "active_customers": active_customers,
        "new_customers": new_customers,
        "repeat_customers": repeat_customers,
        "customer_retention_rate": round(
            (repeat_customers / active_customers * 100) if active_customers > 0 else 0, 2
        ),
    }


def get_dashboard_stats(
    session: Session,
) -> dict:
    """
    Get dashboard statistics for admin.
    """
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    
    # Today's stats
    today_orders = session.exec(
        select(func.count(Order.id)).where(func.date(Order.placed_at) == today)
    ).first() or 0
    
    today_revenue = session.exec(
        select(func.sum(Order.grand_total)).where(
            func.date(Order.placed_at) == today,
            Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED]),
        )
    ).first() or Decimal("0.00")
    
    # This week's stats
    week_orders = session.exec(
        select(func.count(Order.id)).where(Order.placed_at >= start_of_week)
    ).first() or 0
    
    week_revenue = session.exec(
        select(func.sum(Order.grand_total)).where(
            Order.placed_at >= start_of_week,
            Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED]),
        )
    ).first() or Decimal("0.00")
    
    # This month's stats
    month_orders = session.exec(
        select(func.count(Order.id)).where(Order.placed_at >= start_of_month)
    ).first() or 0
    
    month_revenue = session.exec(
        select(func.sum(Order.grand_total)).where(
            Order.placed_at >= start_of_month,
            Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED]),
        )
    ).first() or Decimal("0.00")
    
    # Total orders
    total_orders = session.exec(
        select(func.count(Order.id)).where(
            Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED])
        )
    ).first() or 0
    
    total_revenue = session.exec(
        select(func.sum(Order.grand_total)).where(
            Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CONFIRMED])
        )
    ).first() or Decimal("0.00")
    
    # Pending orders
    pending_orders = session.exec(
        select(func.count(Order.id)).where(Order.status == OrderStatus.PENDING)
    ).first() or 0
    
    # Total products
    total_products = session.exec(select(func.count(Product.id))).first() or 0
    
    return {
        "today": {
            "orders": today_orders,
            "revenue": float(today_revenue),
        },
        "this_week": {
            "orders": week_orders,
            "revenue": float(week_revenue),
        },
        "this_month": {
            "orders": month_orders,
            "revenue": float(month_revenue),
        },
        "total": {
            "orders": total_orders,
            "revenue": float(total_revenue),
            "pending_orders": pending_orders,
            "total_products": total_products,
        },
    }