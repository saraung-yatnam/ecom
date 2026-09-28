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
from app.core.rate_limit import limiter
from app.api.v1.router import api_router
from app.db.database import engine
from app.services.order_expiry import expire_stale_pending_orders


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
    # Disabled during tests (or when a sqlite test DB is in use) so a stray
    # interval job never touches the database.
    started = False
    uses_test_db = settings.DATABASE_URL.startswith("sqlite")
    if settings.ENVIRONMENT != "test" and not uses_test_db:
        _scheduler.add_job(
            _sweep_expired_orders,
            "interval",
            minutes=settings.PENDING_ORDER_EXPIRY_JOB_MINUTES,
            id="expire_pending_orders",
            replace_existing=True,
        )
        _scheduler.start()
        started = True
        print(
            f"🧹 Order-expiry sweep started: every "
            f"{settings.PENDING_ORDER_EXPIRY_JOB_MINUTES} min "
            f"(auto-cancel after {settings.PENDING_ORDER_EXPIRY_MINUTES} min)"
        )
    yield
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


@app.get("/")
def root():
    return {
        "message": "E-Commerce API",
        "environment": settings.ENVIRONMENT,
        "payment_provider": settings.PAYMENT_PROVIDER,
    }


