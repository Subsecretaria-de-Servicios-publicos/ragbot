"""app/services/sovra_client.py — Cliente HTTP mínimo de la API de verificación de Sovra ID.

Solo lo que usa el login al dashboard: crear una sesión de verificación y consultarla. Auth con la
API key del workspace (Authorization: Bearer sovra_sk_...). Los mensajes de error nunca incluyen la
key ni el cuerpo completo de la respuesta.
"""
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.core.config import settings


class SovraError(Exception):
    """Falla al hablar con Sovra (red, HTTP no 2xx o respuesta inesperada)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _validated_base_url(url: str) -> str:
    parsed = urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise SovraError("SOVRA_BASE_URL debe ser https (o http solo hacia localhost)")
    if not parsed.hostname:
        raise SovraError("SOVRA_BASE_URL no es una URL válida")
    return url.rstrip("/")


class SovraClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 timeout: Optional[float] = None, transport: Optional[httpx.AsyncBaseTransport] = None):
        self._base_url = _validated_base_url(base_url if base_url is not None else settings.SOVRA_BASE_URL)
        self._api_key = api_key if api_key is not None else settings.SOVRA_API_KEY
        self._timeout = timeout if timeout is not None else settings.SOVRA_HTTP_TIMEOUT_SECONDS
        self._transport = transport  # solo para tests

    async def _request(self, method: str, path: str, json: Optional[dict] = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as http:
                resp = await http.request(
                    method, f"{self._base_url}{path}", json=json,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.HTTPError as e:
            # type(e).__name__ y no str(e): el texto de algunas excepciones incluye la URL completa
            raise SovraError(f"No se pudo contactar a Sovra ({type(e).__name__})") from e
        if resp.status_code >= 400:
            code = ""
            try:
                body = resp.json()
                code = str(body.get("error", ""))[:60] if isinstance(body, dict) else ""
            except ValueError:
                pass
            raise SovraError(f"Sovra respondió HTTP {resp.status_code} {code}".strip(), status=resp.status_code)
        try:
            data = resp.json()
        except ValueError as e:
            raise SovraError("Sovra devolvió una respuesta que no es JSON", status=resp.status_code) from e
        if not isinstance(data, dict):
            raise SovraError("Sovra devolvió una respuesta inesperada", status=resp.status_code)
        return data

    async def create_verification(self, dcql_query: dict) -> dict:
        return await self._request("POST", "/api/v1/verifier/verifications", json={"dcql_query": dcql_query})

    async def get_verification(self, session_id: str) -> dict:
        return await self._request("GET", f"/api/v1/verifier/verifications/{session_id}")
