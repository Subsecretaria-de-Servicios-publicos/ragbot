"""app/services/sovra_login.py — Login al dashboard con credencial de Sovra ID.

Flujo: start() crea una sesión de verificación en Sovra y un intento de login propio; el navegador
consulta poll() hasta que Sovra confirma la presentación. Entonces se busca al usuario por el DNI de
la credencial y, si existe y está activo, el intento se canjea UNA vez (el router emite los JWT).

La credencial solo prueba quién es: el rol sale siempre de la tabla users. Cualquier motivo de
rechazo (DNI sin usuario, usuario inactivo, emisor distinto, etc.) se informa al navegador como
"failed" sin detalle, para no revelar qué DNIs existen; el motivo real queda en el log.

Persistencia detrás de LoginStore (ver sovra_login_store.py) para poder probar la lógica sin base.
"""
import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, Protocol, Tuple

import structlog

from app.core.config import settings
from app.services.sovra_client import SovraClient, SovraError

logger = structlog.get_logger()

MAX_SOVRA_TTL_SECONDS = 600  # Sovra no deja vivir una sesión de verificación más que esto

_DNI_RE = re.compile(r"\d{6,10}")


def normalize_dni(raw: Any) -> Optional[str]:
    """DNI como solo dígitos ('12.345.678' → '12345678'), o None si no parece un DNI."""
    if raw is None or isinstance(raw, (dict, list, bool)):
        return None
    digits = re.sub(r"[.\s-]", "", str(raw))
    return digits if _DNI_RE.fullmatch(digits) else None


def build_login_dcql(claim: str, vct: str) -> dict:
    """Pide solo el claim identificador y, si hay vct, fija el tipo de credencial aceptado."""
    cred: dict = {"id": "login", "format": "vc+sd-jwt", "claims": [{"path": [claim]}]}
    if vct:
        cred["meta"] = {"vct_values": [vct]}
    return {"credentials": [cred]}


# ─── Lectura de la presentación ──────────────────────────────
# OJO: Sovra documenta presentation_data solo como "object". La forma de abajo sale de la guía de
# webhooks (presentation.verified → credentials[].claims) y NO está verificada contra una
# presentación real. Está aislada acá a propósito: si la forma real es otra, se ajusta esta función.
_ISSUER_KEYS = ("iss", "issuer", "issuer_did")


def _entries(data: Any) -> list:
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    if not isinstance(data, dict):
        return []
    creds = data.get("credentials")
    if isinstance(creds, list):
        return [e for e in creds if isinstance(e, dict)]
    if isinstance(creds, dict):
        return [e for e in creds.values() if isinstance(e, dict)]
    return [data]


def extract_presented(presentation_data: Any, claim: str) -> Tuple[Any, Optional[str]]:
    """(valor del claim, emisor informado) de la primera credencial que traiga el claim."""
    for entry in _entries(presentation_data):
        claims = entry.get("claims") if isinstance(entry.get("claims"), dict) else entry
        if claim in claims:
            issuer = next((entry[k] for k in _ISSUER_KEYS if isinstance(entry.get(k), str)), None)
            return claims[claim], issuer
    return None, None


def issuer_matches(issuer: Optional[str], expected_did: str) -> bool:
    """Sovra informa el emisor como una URL https cuyo path termina en el DID (ver `iss` de sus
    credenciales); también se acepta el DID pelado."""
    if not issuer or not expected_did:
        return False
    issuer = issuer.rstrip("/")
    return issuer == expected_did or issuer.endswith("/" + expected_did)


# ─── Persistencia ────────────────────────────────────────────
@dataclass
class LoginRecord:
    id: str
    sovra_session_id: str
    poll_secret_hash: str
    expires_at: datetime
    status: str = "pending"  # pending | verified | consumed | failed | expired
    purpose: str = "login"  # login | link
    link_user_id: Optional[str] = None  # solo purpose=link: a qué usuario se le vincula el DNI
    user_id: Optional[str] = None
    error: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


@dataclass
class UserRef:
    id: str
    is_active: bool


class LoginStore(Protocol):
    async def create(self, rec: LoginRecord) -> None: ...
    async def get(self, login_id: str) -> Optional[LoginRecord]: ...
    async def update(self, login_id: str, **fields: Any) -> None: ...
    async def consume(self, login_id: str) -> bool:
        """verified → consumed de forma atómica. True solo para quien lo logra (un solo uso)."""
    async def find_user_by_identifier(self, identifier: str) -> Optional[UserRef]: ...
    async def link_identifier(self, user_id: str, identifier: str) -> str:
        """Asigna el DNI al usuario de forma atómica, solo si todavía no tiene uno.
        Devuelve 'ok', 'already_linked' (ya tenía) o 'taken' (lo tiene otro usuario)."""


@dataclass
class StartResult:
    login_id: str
    poll_secret: str  # solo se entrega acá; en la base queda el hash
    uri: str
    expires_at: datetime


@dataclass
class PollResult:
    status: str  # pending | ok | failed | expired
    user_id: Optional[str] = None
    # Solo en 'link' (el usuario ya está autenticado, no hay nada que ocultarle): 'taken' | 'already_linked'
    reason: Optional[str] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_poll_secret(secret: str) -> str:
    # Secreto de alta entropía generado acá: alcanza un hash rápido (igual que las API keys)
    return hashlib.sha256(secret.encode()).hexdigest()


class SovraLoginService:
    def __init__(self, store: LoginStore, client: SovraClient, cfg: Any = settings,
                 clock: Callable[[], datetime] = _utcnow):
        self.store = store
        self.client = client
        self.cfg = cfg
        self.clock = clock

    async def start(self, ip: Optional[str], user_agent: Optional[str],
                    purpose: str = "login", user_id: Optional[str] = None) -> StartResult:
        """purpose='link': `user_id` es el usuario autenticado al que se le vinculará el DNI."""
        if purpose not in ("login", "link") or (purpose == "link") != bool(user_id):
            raise ValueError("purpose/user_id inconsistentes")
        dcql = build_login_dcql(self.cfg.SOVRA_LOGIN_CLAIM, self.cfg.SOVRA_LOGIN_VCT)
        sov = await self.client.create_verification(dcql)
        session_id = sov.get("session_id")
        # La forma corta (_ref) es la que Sovra recomienda para el QR: no crece con el DCQL
        uri = sov.get("authorization_request_uri_ref") or sov.get("authorization_request_uri")
        if not session_id or not uri:
            raise SovraError("Sovra no devolvió session_id o URI de autorización")

        login_id = str(uuid.uuid4())
        poll_secret = secrets.token_urlsafe(32)
        ttl = min(int(self.cfg.SOVRA_LOGIN_TTL_SECONDS), MAX_SOVRA_TTL_SECONDS)
        expires_at = self.clock() + timedelta(seconds=ttl)
        await self.store.create(LoginRecord(
            id=login_id, sovra_session_id=str(session_id),
            poll_secret_hash=hash_poll_secret(poll_secret), expires_at=expires_at,
            purpose=purpose, link_user_id=user_id if purpose == "link" else None,
            ip_address=ip, user_agent=(user_agent or "")[:500] or None,
        ))
        logger.info("sovra_login_started", login_id=login_id, purpose=purpose, ip=ip)
        return StartResult(login_id=login_id, poll_secret=poll_secret, uri=uri, expires_at=expires_at)

    async def poll(self, login_id: str, poll_secret: str, purpose: str = "login",
                   user_id: Optional[str] = None) -> Optional[PollResult]:
        """None = no existe, el secreto no corresponde, o el intento es de otro propósito o de otro
        usuario (el router responde 404 en todos los casos). El propósito se valida acá para que un
        intento de 'link' nunca pueda cobrarse como 'login' ni al revés."""
        rec = await self.store.get(login_id)
        expected = rec.poll_secret_hash if rec else hash_poll_secret("")
        secret_ok = hmac.compare_digest(expected, hash_poll_secret(poll_secret or ""))
        if rec is None or not secret_ok:
            return None
        if rec.purpose != purpose or (purpose == "link" and rec.link_user_id != user_id):
            return None

        if rec.status in ("failed", "consumed"):
            return PollResult("failed", reason=self._public_reason(rec))
        if rec.status == "expired":
            return PollResult("expired")
        if self.clock() >= rec.expires_at:
            await self.store.update(rec.id, status="expired")
            return PollResult("expired")
        if rec.status == "verified":  # quedó verificado pero sin entregar (corte entre medio)
            return await self._deliver(rec)

        try:
            sov = await self.client.get_verification(rec.sovra_session_id)
        except SovraError as e:
            # Falla transitoria de red/Sovra: el intento sigue vivo, el navegador reintenta
            logger.warning("sovra_login_poll_error", login_id=rec.id, error=str(e))
            return PollResult("pending")

        sovra_status = sov.get("status")
        if sovra_status == "completed":
            return await self._complete(rec, sov)
        if sovra_status == "expired":
            await self.store.update(rec.id, status="expired")
            return PollResult("expired")
        if sovra_status == "failed":
            return await self._fail(rec, f"sovra_failed:{str(sov.get('error') or '')[:60]}")
        if sovra_status != "pending":
            logger.warning("sovra_login_unknown_status", login_id=rec.id, sovra_status=str(sovra_status)[:30])
        return PollResult("pending")

    async def _complete(self, rec: LoginRecord, sov: dict) -> PollResult:
        value, issuer = extract_presented(sov.get("presentation_data"), self.cfg.SOVRA_LOGIN_CLAIM)
        dni = normalize_dni(value)
        if dni is None:
            return await self._fail(rec, "no_identifier_in_presentation")
        if self.cfg.SOVRA_LOGIN_ISSUER_DID and not issuer_matches(issuer, self.cfg.SOVRA_LOGIN_ISSUER_DID):
            return await self._fail(rec, "issuer_mismatch")
        if rec.purpose == "link":
            return await self._complete_link(rec, dni)
        user = await self.store.find_user_by_identifier(dni)
        if user is None:
            return await self._fail(rec, "no_user_for_identifier")
        if not user.is_active:
            return await self._fail(rec, "user_inactive")
        await self.store.update(rec.id, status="verified", user_id=user.id)
        rec.user_id = user.id
        return await self._deliver(rec)

    async def _complete_link(self, rec: LoginRecord, dni: str) -> PollResult:
        outcome = await self.store.link_identifier(rec.link_user_id, dni)
        if outcome != "ok":
            return await self._fail(rec, f"link_{outcome}")
        await self.store.update(rec.id, status="verified", user_id=rec.link_user_id)
        rec.user_id = rec.link_user_id
        logger.info("sovra_link_ok", login_id=rec.id, user_id=rec.link_user_id)
        return await self._deliver(rec)

    @staticmethod
    def _public_reason(rec: LoginRecord) -> Optional[str]:
        if rec.purpose == "link" and rec.error and rec.error.startswith("link_"):
            return rec.error[len("link_"):]
        return None

    async def _deliver(self, rec: LoginRecord) -> PollResult:
        if not await self.store.consume(rec.id):
            logger.warning("sovra_login_replay", login_id=rec.id)
            return PollResult("failed")
        logger.info("sovra_login_ok", login_id=rec.id, user_id=rec.user_id)
        return PollResult("ok", user_id=rec.user_id)

    async def _fail(self, rec: LoginRecord, reason: str) -> PollResult:
        await self.store.update(rec.id, status="failed", error=reason)
        rec.error = reason
        logger.warning("sovra_login_rejected", login_id=rec.id, purpose=rec.purpose, reason=reason)
        return PollResult("failed", reason=self._public_reason(rec))
