"""app/core/net.py — Resolución de la IP real del cliente detrás de un proxy."""
from fastapi import Request

from app.core.config import settings


def get_client_ip(request: Request) -> str:
    """IP del cliente para rate limiting y logging.

    Si TRUST_PROXY_HEADERS está activo (la app corre detrás del nginx de
    docker-compose.yml u otro proxy de confianza), usa X-Forwarded-For/X-Real-IP
    para identificar al cliente real en vez del proxy. Si no, usa la conexión TCP
    directa: confiar en esos headers sin un proxy real por delante permitiría a
    cualquiera falsificarlos y evadir el rate limit.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    return request.client.host if request.client else "unknown"
