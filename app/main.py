from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.router import api_router


app = FastAPI(title=settings.PROJECT_NAME)

# Debug: Print CORS settings
print(f"CORS_ORIGINS: {settings.CORS_ORIGINS}")
print(f"CORS_ORIGINS_LIST: {settings.cors_origins_list}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def root():
    return {
        "message": "E-Commerce API",
        "environment": settings.ENVIRONMENT,
        "payment_provider": settings.PAYMENT_PROVIDER,
    }