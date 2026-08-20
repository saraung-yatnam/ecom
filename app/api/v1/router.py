from fastapi import APIRouter
from app.api.v1 import auth,product,product_images,cart,checkout,address,orders,admin,payments,webhooks
api_router=APIRouter()

api_router.include_router(auth.router)
api_router.include_router(product.router)
api_router.include_router(product_images.router)
api_router.include_router(cart.router)
api_router.include_router(checkout.router)
api_router.include_router(address.router)
api_router.include_router(orders.router)
api_router.include_router(admin.router) 
api_router.include_router(payments.router)
api_router.include_router(webhooks.router)