from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlmodel import Session
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.release import validate_production_settings, assert_database_ready
from app.core.rate_limit import limiter
from app.api.v1.router import api_router
from app.db.database import engine
from app.services.order_expiry import expire_stale_pending_orders
from app.services.email_outbox import deliver_pending_emails


def _deliver_email_outbox():
    try:
        with Session(engine) as session:
            deliver_pending_emails(session)
    except Exception as exc:
        print(f"Email outbox delivery failed: {exc}")


def _sweep_expired_orders() -> None:
    """APScheduler job: auto-cancel abandoned unpaid online orders."""
    try:
        with Session(engine) as session:
            result = expire_stale_pending_orders(session)
        if result["cancelled"]:
            print(
                f"🧹 Auto-cancelled {result['cancelled']} abandoned order(s): "
                f"{', '.join(result['order_numbers']) or '-'}"
            )
    except Exception as e:
        print(f"❌ Order-expiry sweep failed: {e}")


_scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    production = settings.ENVIRONMENT.lower() == "production"
    if production:
        validate_production_settings(settings)
        assert_database_ready(engine)
    # Disabled during tests (or when a sqlite test DB is in use) so a stray
    # interval job never touches the database.
    started = False
    uses_test_db = settings.DATABASE_URL.startswith("sqlite")
    if settings.ENVIRONMENT == "test" or uses_test_db:
        yield
        return
    # Guarantee the store_settings singleton exists before serving, so
    # request handlers (notably GET) never have to write. A failed seed
    # never crashes boot — reads degrade to env defaults.
    try:
        from app.core.store_settings import seed_store_settings

        with Session(engine) as session:
            seed_store_settings(session)
    except Exception as exc:
        if production:
            raise RuntimeError("Production store-policy initialization failed") from exc
        print(f"⚠️ store_settings startup seed failed ({type(exc).__name__}: {exc})")
    _scheduler.add_job(
        _sweep_expired_orders,
        "interval",
        minutes=settings.PENDING_ORDER_EXPIRY_JOB_MINUTES,
        id="expire_pending_orders",
        replace_existing=True,
    )
    _scheduler.add_job(_deliver_email_outbox, "interval", seconds=30,
                       id="deliver_email_outbox", replace_existing=True, max_instances=1)
    _scheduler.start()
    started = True
    print(
        f"🧹 Order-expiry sweep started: every "
        f"{settings.PENDING_ORDER_EXPIRY_JOB_MINUTES} min "
        f"(auto-cancel after {settings.PENDING_ORDER_EXPIRY_MINUTES} min)"
    )
    try:
        yield
    finally:
        if started:
            _scheduler.shutdown(wait=False)


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class CatchAllExceptionsMiddleware:
    """
    Converts unhandled exceptions into a JSON 500 response.

    Without this, an unhandled 500 is sent by Starlette's OUTERMOST error
    middleware — bypassing CORSMiddleware — so the response has no CORS
    headers and the browser reports a misleading CORS error instead of the
    real 500. Registered INNER to CORSMiddleware (added before it), so its
    responses still get CORS headers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            print(f"❌ Unhandled error on {scope.get('method')} {scope.get('path')}: {type(exc).__name__}: {exc}")
            try:
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "Internal server error"},
                )
                await response(scope, receive, send)
            except Exception:
                # Response already started — nothing more we can do
                pass


# Inner middleware first...
app.add_middleware(CatchAllExceptionsMiddleware)

# ...then CORS (added last = outermost after Starlette's error middleware,
# so it stamps CORS headers on every response, including our JSON 500s)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Debug: Print CORS settings
print(f"CORS_ORIGINS: {settings.CORS_ORIGINS}")
print(f"CORS_ORIGINS_LIST: {settings.cors_origins_list}")

app.include_router(api_router, prefix="/api/v1")


# User-uploaded content (banner/hero images). Served straight from disk;
# back up the uploads/ dir — it is user content, not code. The directory is
# created on boot so a fresh clone serves (empty) instead of 500ing.
from pathlib import Path as _Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_UPLOADS_DIR = _Path(__file__).resolve().parent.parent / "uploads"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_UPLOADS_DIR)), name="uploads")


@app.get("/")
def root():
    return {
        "message": "E-Commerce API",
        "environment": settings.ENVIRONMENT,
        "payment_provider": settings.PAYMENT_PROVIDER,
    }


@app.get("/health/live")
def liveness():
    return {"status": "alive"}


@app.get("/health/ready")
def readiness():
    try:
        validate_production_settings(settings)
        assert_database_ready(engine)
        if settings.ENVIRONMENT.lower() == "production":
            if not _scheduler.running or any(_scheduler.get_job(key) is None for key in ("expire_pending_orders", "deliver_email_outbox")):
                raise RuntimeError("Commerce background jobs unavailable")
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
