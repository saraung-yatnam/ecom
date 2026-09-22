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

    # Payment
    PAYMENT_PROVIDER: str = "dummy"
    PAYMENT_CURRENCY: str = "INR"
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: str | None = None
    RAZORPAY_WEBHOOK_SECRET: str | None = None
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_PUBLISHABLE_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None

    # Email (SendGrid)
    SENDGRID_API_KEY: str | None = None
    FROM_EMAIL: str = "noreply@yourstore.com"

    # Google OAuth
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None

    # Password Reset Settings
    FRONTEND_URL: str = "http://localhost:5173"
    RESET_TOKEN_EXPIRE_HOURS: int = 1

    # ========== NEW: Tax & Shipping Settings ==========
    TAX_RATE: float = 0.18  # 18% GST
    FREE_SHIPPING_THRESHOLD: float = 1000.00
    SHIPPING_COST: float = 50.00

    # ========== COD (Cash on Delivery) Settings ==========
    COD_FEE: float = 50.00                 # flat fee added to COD orders
    COD_MIN_ORDER_VALUE: float = 0.00      # grand_total must be >= this for COD
    COD_MAX_ORDER_VALUE: float = 10000.00  # grand_total must be <= this for COD

    # ========== Cancellation & Refund Settings ==========
    REFUND_PROCESSING_DAYS: int = 5           # days for refund to reflect in account
    RESTOCKING_FEE_PENDING: float = 0.0       # % fee when cancelling a PENDING order
    RESTOCKING_FEE_CONFIRMED: float = 5.0     # % fee when cancelling a CONFIRMED order
    RESTOCKING_FEE_PROCESSING: float = 15.0   # % fee when cancelling a PROCESSING order

    # ========== Abandoned unpaid online orders ==========
    # Online orders that are still PENDING/payment_status "pending" longer than
    # PENDING_ORDER_EXPIRY_MINUTES get auto-cancelled by the sweep job (stock
    # restored, provider PaymentIntent cancelled, customer emailed).
    PENDING_ORDER_EXPIRY_MINUTES: int = 30
    # How often the sweep job runs (seconds between runs via APScheduler)
    PENDING_ORDER_EXPIRY_JOB_MINUTES: int = 2

    GEMINI_API_KEY:str|None=None
    HUGGING_FACE_API_KEY:str|None=None
    GROQ_API_KEY:str|None=None

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()

# Debug prints
print(f"PAYMENT_PROVIDER: {settings.PAYMENT_PROVIDER}")
print(f"RAZORPAY_KEY_ID: {settings.RAZORPAY_KEY_ID}")
print(f"RAZORPAY_KEY_SECRET: {'***' if settings.RAZORPAY_KEY_SECRET else 'None'}")
print(f"FRONTEND_URL: {settings.FRONTEND_URL}")
print(f"RESET_TOKEN_EXPIRE_HOURS: {settings.RESET_TOKEN_EXPIRE_HOURS}")
print(f"TAX_RATE: {settings.TAX_RATE}")
print(f"FREE_SHIPPING_THRESHOLD: {settings.FREE_SHIPPING_THRESHOLD}")
print(f"SHIPPING_COST: {settings.SHIPPING_COST}")