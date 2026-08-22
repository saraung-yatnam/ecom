from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # App
    PROJECT_NAME: str = "E-Commerce API"
    ENVIRONMENT: str = "development"

    # DB
    DATABASE_URL: str

    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # CORS
    CORS_ORIGINS: str = "*"

    # 👇 PAYMENT - ADD THESE FIELDS
    PAYMENT_PROVIDER: str = "dummy"
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: str | None = None
    RAZORPAY_WEBHOOK_SECRET: str | None = None

    # Email (SendGrid)
    SENDGRID_API_KEY: str | None = None
    FROM_EMAIL: str = "noreply@yourstore.com"

    # Google OAuth
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()

# 👇 Debug prints
print(f"PAYMENT_PROVIDER: {settings.PAYMENT_PROVIDER}")
print(f"RAZORPAY_KEY_ID: {settings.RAZORPAY_KEY_ID}")
print(f"RAZORPAY_KEY_SECRET: {'***' if settings.RAZORPAY_KEY_SECRET else 'None'}")