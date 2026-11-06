"""app/services/sovra_login.py — Login al dashboard con credencial de Sovra ID.

Flujo: start() crea una sesión de verificación en Sovra y un intento de login propio; el navegador
consulta poll() hasta que Sovra confirma la presentación. Entonces se busca al usuario por el
holder_did de la presentación y, si existe, está activo y su DNI coincide con el de la credencial,
el intento se canjea UNA vez (el router emite los JWT).

Sovra no informa emisor ni tipo de credencial en el resultado, así que el DNI solo no alcanza (otra
credencial con el DNI de un usuario serviría). Lo que ata el login a una persona es el holder_did,
que se guarda cuando el usuario, ya logueado con su contraseña, vincula su wallet (purpose='link').
Sin vinculación previa no hay login por Sovra, aunque el admin le haya cargado el DNI.

La credencial solo prueba quién es: el rol sale siempre de la tabla users. Cualquier motivo de
rechazo (holder sin vincular, usuario inactivo, DNI distinto, etc.) se informa al navegador como
"failed" sin detalle, para no revelar qué cuentas existen; el motivo real queda en el log.

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
MAX_HOLDER_DID_LEN = 255  # largo de users.sovra_holder_did

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
# Forma documentada por Sovra para una verificación completada (confirmada por ellos con un ejemplo
# real): presentation_data.credentials[] = {id, format, claims}, donde `id` es el de la consulta DCQL y
# `claims` trae los datos pedidos con el mismo nombre. El emisor y el tipo NO vienen. El holder_did
# viene al nivel de la verificación, no dentro de presentation_data.
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


def extract_presented(presentation_data: Any, claim: str) -> Any:
    """Valor del claim en la primera credencial que lo traiga (None si no está)."""
    for entry in _entries(presentation_data):
        claims = entry.get("claims") if isinstance(entry.get("claims"), dict) else entry
        if claim in claims:
            return claims[claim]
    return None


def normalize_holder_did(raw: Any) -> Optional[str]:
    """El holder_did tal cual lo informa Sovra, o None si falta o no es un texto razonable."""
    if not isinstance(raw, str):
        return None
    did = raw.strip()
    return did if did.startswith("did:") and len(did) <= MAX_HOLDER_DID_LEN else None


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
    identifier: Optional[str] = None  # DNI del usuario (users.sovra_identifier)


class LoginStore(Protocol):
    async def create(self, rec: LoginRecord) -> None: ...
    async def get(self, login_id: str) -> Optional[LoginRecord]: ...
    async def update(self, login_id: str, **fields: Any) -> None: ...
    async def consume(self, login_id: str) -> bool:
        """verified → consumed de forma atómica. True solo para quien lo logra (un solo uso)."""
    async def find_user_by_holder(self, holder_did: str) -> Optional[UserRef]: ...
    async def link_identity(self, user_id: str, identifier: str, holder_did: str) -> str:
        """Guarda DNI + holder_did del usuario de forma atómica. Solo si todavía no tiene wallet
        vinculada y su DNI está sin cargar o ya es este (el que le asignó el admin).
        Devuelve 'ok', 'already_linked' (ya tenía wallet), 'mismatch' (tiene otro DNI cargado) o
        'taken' (el DNI o el holder_did ya son de otro usuario)."""


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
    # Solo en 'link' (el usuario ya está autenticado, no hay nada que ocultarle):
    # 'taken' | 'already_linked' | 'mismatch'
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
        dni = normalize_dni(extract_presented(sov.get("presentation_data"), self.cfg.SOVRA_LOGIN_CLAIM))
        if dni is None:
            return await self._fail(rec, "no_identifier_in_presentation")
        holder = normalize_holder_did(sov.get("holder_did"))
        if holder is None:
            return await self._fail(rec, "no_holder_did")
        if rec.purpose == "link":
            return await self._complete_link(rec, dni, holder)
        user = await self.store.find_user_by_holder(holder)
        if user is None:
            return await self._fail(rec, "holder_not_linked")
        if not user.is_active:
            return await self._fail(rec, "user_inactive")
        if user.identifier != dni:  # el admin le cambió el DNI y todavía no revinculó, o credencial distinta
            return await self._fail(rec, "identifier_mismatch")
        await self.store.update(rec.id, status="verified", user_id=user.id)
        rec.user_id = user.id
        return await self._deliver(rec)

    async def _complete_link(self, rec: LoginRecord, dni: str, holder: str) -> PollResult:
        outcome = await self.store.link_identity(rec.link_user_id, dni, holder)
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
