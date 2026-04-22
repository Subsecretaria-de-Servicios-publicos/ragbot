"""
app/main.py — FastAPI application principal con CORS, headers de seguridad y middleware
"""
import time
import uuid
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os

from app.core.config import settings
from app.api.routers import (
    auth_router, users_router, chatbots_router,
    documents_router, chat_router, analytics_router,
)

logger = structlog.get_logger()

# ─── App Instance ─────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
)

# ─── CORS ─────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=settings.ALLOWED_METHODS.split(","),
    allow_headers=settings.ALLOWED_HEADERS.split(",") if settings.ALLOWED_HEADERS != "*" else ["*"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
    max_age=86400,  # Cache preflight 24h
)

# ─── GZip ─────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ─── Security Headers Middleware ──────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if not settings.DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ─── Request ID + Logging Middleware ──────────────────────────
@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.monotonic()
    request.state.request_id = request_id

    response = await call_next(request)
    duration = int((time.monotonic() - start) * 1000)

    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration,
        request_id=request_id,
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{duration}ms"
    return response


# ─── Rate Limiting (simple Redis-based) ───────────────────────
@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    # Excluir rutas estáticas y health check
    if request.url.path in ("/health", "/") or request.url.path.startswith("/static"):
        return await call_next(request)

    try:
        import redis.asyncio as redis_async
        r = redis_async.from_url(settings.REDIS_URL, decode_responses=True)
        key = f"rl:{request.client.host}:{request.url.path}"
        current = await r.incr(key)
        if current == 1:
            await r.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS)
        await r.aclose()

        if current > settings.RATE_LIMIT_REQUESTS:
            return JSONResponse(
                status_code=429,
                content={"detail": "Demasiadas solicitudes. Intenta más tarde."},
                headers={"Retry-After": str(settings.RATE_LIMIT_WINDOW_SECONDS)},
            )
    except Exception:
        pass  # Si Redis no está disponible, no bloquear

    return await call_next(request)


# ─── Routers ──────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(chatbots_router, prefix=API_PREFIX)
app.include_router(documents_router, prefix=API_PREFIX)
app.include_router(chat_router, prefix=API_PREFIX)
app.include_router(analytics_router, prefix=API_PREFIX)

# ─── Static Files (widget JS, dashboard) ──────────────────────
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Health Check ─────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/")
async def root():
    return {"name": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/api/docs"}


# ─── Startup ──────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    logger.info("ragbot_started", version=settings.APP_VERSION)
