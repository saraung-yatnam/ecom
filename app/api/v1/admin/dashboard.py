from datetime import datetime
from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import SessionDep, require_role
from app.models.user import User, UserRole
from app.repositories import user as user_repo  # 👈 Use existing user repo
from app.repositories import order as order_repo
from app.repositories import analytics as analytics_repo
from app.repositories import product as product_repo

router = APIRouter(prefix="/admin/dashboard", tags=["Admin Dashboard"])


@router.get("", response_model=dict)
def get_admin_dashboard(
    session: SessionDep,
    current_user: User = Depends(require_role(UserRole.admin,UserRole.manager)),
):
    """
    Get admin dashboard summary.
    
    Allowed:
        admin
    """
    # User stats
    user_stats = user_repo.get_user_stats(session)
    
    # Order stats
    order_stats = order_repo.get_order_statistics(session)
    
    # Revenue stats
    revenue_stats = analytics_repo.get_dashboard_stats(session)
    
    # Recent orders
    recent_orders = order_repo.get_recent_orders(session, limit=10)
    
    # Total products
    total_products = product_repo.get_total_products(session)
    
    return {
        "users": user_stats,
        "orders": order_stats,
        "revenue": revenue_stats,
        "total_products": total_products,
        "recent_orders": recent_orders,
        "timestamp": datetime.now().isoformat(),
    }