from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.api.v1.router import api_router

app = FastAPI(title=settings.PROJECT_NAME)


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


