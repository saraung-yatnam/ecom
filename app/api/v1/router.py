from fastapi import APIRouter
from app.api.v1 import auth,product,product_images,categories,cart,checkout,address,orders,payments,webhooks,reviews,wishlist,coupons,email,analytics
from app.api.v1.admin import dashboard, orders as admin_orders, users as admin_users, products as admin_products
from app.api.v1.admin import cod as admin_cod

api_router=APIRouter()


api_router.include_router(auth.router)
api_router.include_router(product.router)
api_router.include_router(categories.router)
api_router.include_router(product_images.router)
api_router.include_router(cart.router)
api_router.include_router(checkout.router)
api_router.include_router(address.router)
api_router.include_router(orders.router)
api_router.include_router(payments.router)
api_router.include_router(webhooks.router)
api_router.include_router(reviews.router)
api_router.include_router(wishlist.router)
api_router.include_router(coupons.router)
api_router.include_router(email.router)  # Add this
api_router.include_router(analytics.router)

# Admin APIs
api_router.include_router(dashboard.router)        # /admin/dashboard
api_router.include_router(admin_orders.router)     # /admin/orders
api_router.include_router(admin_users.router)      # /admin/users
api_router.include_router(admin_products.router)   # /admin/products
api_router.include_router(admin_cod.router)        # /admin/cod