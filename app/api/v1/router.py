from fastapi import APIRouter
from app.api.v1 import auth,product,product_images,cart


api_router=APIRouter()

api_router.include_router(auth.router)
api_router.include_router(product.router)
api_router.include_router(product_images.router)
api_router.include_router(cart.router)
