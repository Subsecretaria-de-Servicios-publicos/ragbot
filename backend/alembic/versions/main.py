"""
app/main.py — FIX #8: lifespan reemplaza on_event (deprecado)
              FIX #19: pool Redis global en lugar de instancia por request
"""
import time
import uuid
import structlog
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.api.routers import (
    auth_router, users_router, chatbots_router,
    documents_router, chat_router, analytics_router,
)

logger = structlog.get_logger()

# FIX #19: pool Redis global, inicializado en startup
_redis_client = None


# FIX #8: lifespan reemplaza @app.on_event("startup") deprecado
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────
    global _redis_client
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs("static", exist_ok=True)
    try:
        import redis.asyncio as redis_async
        _redis_client = redis_async.from_url(
            settings.REDIS_URL, decode_responses=True,
            max_connections=20,  # pool de conexiones
        )
        await _redis_client.ping()
        logger.info("redis_connected", url=settings.REDIS_URL)
    except Exception as e:
        logger.warning("redis_unavailable", error=str(e), hint="Rate limiting desactivado")
        _redis_client = None
    logger.info("ragbot_started", version=settings.APP_VERSION)
    yield
    # ── Shutdown ─────────────────────────────────────────────
    if _redis_client:
        await _redis_client.aclose()
    logger.info("ragbot_stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


# ─── CORS ─────────────────────────────────────────────────────
def _expand_origins(origins: list[str]) -> list[str]:
    expanded = set(origins)
    for origin in origins:
        try:
            proto, rest = origin.split("://", 1)
            parts = rest.split(":", 1)
            port = parts[1] if len(parts) > 1 else ("443" if proto == "https" else "80")
            for host in ("localhost", "127.0.0.1", "0.0.0.0"):
                expanded.add(f"{proto}://{host}:{port}")
        except Exception:
            pass
    result = sorted(expanded)
    logger.info("cors_origins", origins=result)
    return result


app.add_middleware(
    CORSMiddleware,
    allow_origins=_expand_origins(settings.allowed_origins_list),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time", "X-RateLimit-Remaining"],
    max_age=86400,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# ─── Security Headers ─────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if not settings.DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ─── Request Logging ──────────────────────────────────────────
@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start = time.monotonic()
    request.state.request_id = request_id
    response = await call_next(request)
    duration = int((time.monotonic() - start) * 1000)
    logger.info("http_request", method=request.method, path=request.url.path,
                status=response.status_code, duration_ms=duration, request_id=request_id)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{duration}ms"
    return response


# ─── Rate Limiting — FIX #19: usa pool global ─────────────────
@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    if request.url.path in ("/health", "/") or request.url.path.startswith("/static"):
        return await call_next(request)
    if _redis_client:
        try:
            key = f"rl:{request.client.host}:{request.url.path}"
            current = await _redis_client.incr(key)
            if current == 1:
                await _redis_client.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS)
            if current > settings.RATE_LIMIT_REQUESTS:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Demasiadas solicitudes. Intenta más tarde."},
                    headers={"Retry-After": str(settings.RATE_LIMIT_WINDOW_SECONDS)},
                )
        except Exception:
            pass  # Si Redis falla, no bloquear
    return await call_next(request)


# ─── Routers ──────────────────────────────────────────────────
API_PREFIX = "/api/v1"
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(chatbots_router, prefix=API_PREFIX)
app.include_router(documents_router, prefix=API_PREFIX)
app.include_router(chat_router, prefix=API_PREFIX)
app.include_router(analytics_router, prefix=API_PREFIX)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}


@app.get("/")
async def root():
    return {"name": settings.APP_NAME, "version": settings.APP_VERSION}
