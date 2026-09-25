"""
app/api/routers.py — Todos los endpoints FastAPI
"""
import os
import re
import json
import html
import uuid
import asyncio
import secrets
import hashlib
import aiofiles
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks, Request
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from sqlalchemy import select, func, update, delete, text, or_
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr
import structlog

from app.db.session import get_db
from app.services.alert_service import notify_bot_failure, notify_bot_event
from app.models.models import (
    User, Chatbot, Document, DocumentChunk, Conversation, Message,
    UserRole, DocumentStatus, APIKey, AIProviderConfig, ChatbotAssignment,
)
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user_payload, require_role,
)
from app.core.config import settings
from app.core.net import get_client_ip
from app.core.crypto import encrypt_secret, decrypt_secret, scrub_secrets
from app.services.bot_keys import BotUnavailable, MSG_UNAVAILABLE, month_usage, current_month
from app.services.chat_service import ChatService
from app.services.rag_service import RAGService

logger = structlog.get_logger()

# Ruta al chat.html (relativa a donde corre uvicorn, o absoluta)
CHAT_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "widget", "chat.html")


# ═══════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    user_id: str

class ChatRequest(BaseModel):
    message: str
    session_id: str
    user_identifier: Optional[str] = None

class ChatbotCreate(BaseModel):
    name: str
    description: Optional[str] = None
    ai_provider: str = "google"
    ai_model: str = "gemini-1.5-flash"
    temperature: float = 0.7
    max_tokens: int = 1000
    system_prompt: Optional[str] = None
    welcome_message: str = "¡Hola! ¿En qué puedo ayudarte?"
    bot_name: str = "Asistente"
    bot_avatar_url: Optional[str] = None
    widget_config: Optional[dict] = None
    top_k: int = 5
    similarity_threshold: float = 0.7
    is_public: bool = False

class ChatbotUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    bot_name: Optional[str] = None
    widget_config: Optional[dict] = None
    top_k: Optional[int] = None
    similarity_threshold: Optional[float] = None
    is_active: Optional[bool] = None
    is_public: Optional[bool] = None
    monthly_token_limit: Optional[int] = None  # solo admin; 0 = sin límite

class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.viewer

class APIKeyCreate(BaseModel):
    name: str = "Default"
    allowed_origins: Optional[List[str]] = None

class APIKeyUpdate(BaseModel):
    name: Optional[str] = None
    allowed_origins: Optional[List[str]] = None
    is_active: Optional[bool] = None


def _hash_api_key(raw_key: str) -> str:
    # Las API keys ya son secretos de alta entropía generados por el server:
    # alcanza un hash rápido (a diferencia de las contraseñas, que usan bcrypt).
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario desactivado")
    payload = {"sub": user.id, "username": user.username, "role": user.role.value}
    await db.execute(update(User).where(User.id == user.id).values(last_login=datetime.now(timezone.utc)))
    await db.commit()
    return TokenResponse(
        access_token=create_access_token(payload),
        refresh_token=create_refresh_token(payload),
        role=user.role.value,
        user_id=user.id,
    )


@auth_router.post("/refresh")
async def refresh_token(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    # El token va en el body (no en query string) para que no termine en logs/historial del navegador.
    payload = decode_token(data.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token inválido")
    user = await db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Usuario inactivo o inexistente")
    new_payload = {"sub": user.id, "username": user.username, "role": user.role.value}
    return {"access_token": create_access_token(new_payload), "token_type": "bearer"}


@auth_router.get("/me")
async def me(payload: dict = Depends(get_current_user_payload), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"id": user.id, "email": user.email, "username": user.username,
            "role": user.role.value, "full_name": user.full_name}


# ═══════════════════════════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════════════════════════

users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("/")
async def list_users(payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [{"id": u.id, "email": u.email, "username": u.username,
             "role": u.role.value, "is_active": u.is_active} for u in users]


@users_router.post("/", status_code=201)
async def create_user(data: UserCreate, payload: dict = Depends(require_role("superadmin")), db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email ya registrado")
    user = User(email=data.email, username=data.username,
                hashed_password=hash_password(data.password),
                full_name=data.full_name, role=data.role)
    db.add(user)
    await db.commit()
    return {"id": user.id, "email": user.email, "role": user.role.value}


@users_router.patch("/{user_id}")
async def update_user(user_id: str, data: dict, payload: dict = Depends(require_role("superadmin")), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    for k, v in data.items():
        if hasattr(user, k) and k not in ("id", "hashed_password"):
            setattr(user, k, v)
    if "password" in data:
        user.hashed_password = hash_password(data["password"])
    await db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# CHATBOTS
# ═══════════════════════════════════════════════════════════════

chatbots_router = APIRouter(prefix="/chatbots", tags=["chatbots"])


def _make_slug(name: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return f"{slug}-{str(uuid.uuid4())[:8]}"


# Campos que un usuario asignado (no dueño, no admin/superadmin) puede editar de un bot.
# El resto (proveedor/modelo de IA, temperatura, is_public, is_active, etc.) queda reservado
# a admin/superadmin — separa "qué bot puede tocar" (asignación) de "qué le permite su rol".
ASSIGNEE_EDITABLE_FIELDS = {"description", "system_prompt", "welcome_message", "bot_name", "widget_config"}


async def _is_assigned(bot_id: str, user_id: str, db: AsyncSession) -> bool:
    result = await db.execute(
        select(ChatbotAssignment.id)
        .where(ChatbotAssignment.chatbot_id == bot_id, ChatbotAssignment.user_id == user_id)
    )
    return result.scalar_one_or_none() is not None


async def _get_owned_chatbot(bot_id: str, payload: dict, db: AsyncSession) -> Chatbot:
    """Devuelve el chatbot si el usuario es superadmin/admin, su dueño, o tiene una asignación
    puntual sobre ese bot; 404 en caso contrario (para no revelar bots de otros usuarios)."""
    bot = await db.get(Chatbot, bot_id)
    if not bot:
        raise HTTPException(404, "Chatbot no encontrado")
    if payload["role"] in ("superadmin", "admin") or bot.owner_id == payload["sub"]:
        return bot
    if await _is_assigned(bot_id, payload["sub"], db):
        return bot
    raise HTTPException(404, "Chatbot no encontrado")


def _visible_bot_ids(payload: dict):
    """Subquery con los ids de los bots que el usuario puede ver (dueño o asignado);
    None si ve todos (superadmin/admin). Misma regla que _get_owned_chatbot."""
    if payload["role"] in ("superadmin", "admin"):
        return None
    assigned_ids = select(ChatbotAssignment.chatbot_id).where(ChatbotAssignment.user_id == payload["sub"])
    return select(Chatbot.id).where(or_(Chatbot.owner_id == payload["sub"], Chatbot.id.in_(assigned_ids)))


@chatbots_router.get("/")
async def list_chatbots(payload: dict = Depends(get_current_user_payload), db: AsyncSession = Depends(get_db)):
    query = select(Chatbot)
    visible = _visible_bot_ids(payload)
    if visible is not None:
        query = query.where(Chatbot.id.in_(visible))
    result = await db.execute(query.order_by(Chatbot.created_at.desc()))
    bots = result.scalars().all()
    return [{"id": b.id, "name": b.name, "slug": b.slug, "is_active": b.is_active,
             "ai_provider": b.ai_provider.value, "ai_model": b.ai_model,
             "total_conversations": b.total_conversations,
             "total_messages": b.total_messages,
             "total_tokens_used": b.total_tokens_used,
             "has_ai_key": bool(b.ai_api_key_encrypted) or b.ai_provider.value == "ollama"} for b in bots]


@chatbots_router.post("/", status_code=201)
async def create_chatbot(data: ChatbotCreate, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    bot = Chatbot(**data.model_dump(), slug=_make_slug(data.name), owner_id=payload["sub"])
    db.add(bot)
    await db.commit()
    return {"id": bot.id, "slug": bot.slug, "name": bot.name}


@chatbots_router.get("/{bot_id}")
async def get_chatbot(bot_id: str, payload: dict = Depends(get_current_user_payload), db: AsyncSession = Depends(get_db)):
    bot = await _get_owned_chatbot(bot_id, payload, db)
    return {
        "id": bot.id, "name": bot.name, "slug": bot.slug,
        "description": bot.description, "is_active": bot.is_active,
        "is_public": bot.is_public, "owner_id": bot.owner_id,
        "ai_provider": bot.ai_provider.value, "ai_model": bot.ai_model,
        "temperature": bot.temperature, "max_tokens": bot.max_tokens,
        "system_prompt": bot.system_prompt, "welcome_message": bot.welcome_message,
        "bot_name": bot.bot_name, "bot_avatar_url": bot.bot_avatar_url, "org_logo_url": bot.org_logo_url,
        "widget_config": bot.widget_config, "top_k": bot.top_k,
        "similarity_threshold": bot.similarity_threshold,
        "total_conversations": bot.total_conversations,
        "total_messages": bot.total_messages,
        "total_tokens_used": bot.total_tokens_used,
        "created_at": bot.created_at.isoformat(),
        # API key propia: solo su estado. El valor no sale nunca; el detalle (últimos 4, quién/cuándo) solo para admin.
        "has_ai_key": bool(bot.ai_api_key_encrypted),
        **({"ai_key_hint": bot.ai_api_key_hint,
            "ai_key_updated_at": bot.ai_api_key_updated_at.isoformat() if bot.ai_api_key_updated_at else None}
           if payload["role"] in ("superadmin", "admin") else {}),
        "monthly_token_limit": bot.monthly_token_limit,
        "usage_month": current_month(),
        "usage_month_tokens": month_usage(bot),
    }


@chatbots_router.patch("/{bot_id}")
async def update_chatbot(bot_id: str, data: ChatbotUpdate, payload: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    bot = await _get_owned_chatbot(bot_id, payload, db)
    updates = data.model_dump(exclude_none=True)
    is_admin_or_owner = payload["role"] in ("superadmin", "admin") or bot.owner_id == payload["sub"]
    if not is_admin_or_owner:
        disallowed = set(updates) - ASSIGNEE_EDITABLE_FIELDS
        if disallowed:
            raise HTTPException(403, f"No tenés permiso para editar: {', '.join(sorted(disallowed))}")
    if "monthly_token_limit" in updates:
        # Control de gasto: solo admin/superadmin (aunque el operator sea dueño del bot)
        if payload["role"] not in ("superadmin", "admin"):
            raise HTTPException(403, "Solo un administrador puede cambiar el límite mensual de tokens")
        if updates["monthly_token_limit"] < 0:
            raise HTTPException(400, "El límite mensual no puede ser negativo")
        updates["monthly_token_limit"] = updates["monthly_token_limit"] or None  # 0 = sin límite
    if "ai_provider" in updates and updates["ai_provider"] != bot.ai_provider.value and bot.ai_api_key_encrypted:
        # La key pertenece al proveedor anterior: se descarta (hay que cargar la del nuevo)
        bot.ai_api_key_encrypted = bot.ai_api_key_hint = None
        bot.ai_api_key_updated_at, bot.ai_api_key_updated_by = datetime.now(timezone.utc), payload["sub"]
        logger.info("bot_api_key_cleared_provider_change", bot_id=bot.id, by=payload["sub"])
    for k, v in updates.items():
        setattr(bot, k, v)
    await db.commit()
    return {"ok": True}


class BotApiKeyUpdate(BaseModel):
    # Sin constraints de pydantic a propósito: un error de validación (422) devuelve el valor recibido
    # y no queremos que una key vuelva en una respuesta. Se valida a mano, sin repetirla.
    api_key: str


@chatbots_router.put("/{bot_id}/ai-key")
async def set_bot_api_key(bot_id: str, data: BotApiKeyUpdate, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """Guarda (cifrada) la API key propia del bot. Solo admin/superadmin. Se verifica contra el
    proveedor antes de guardarla y jamás se devuelve."""
    bot = await _get_owned_chatbot(bot_id, payload, db)
    provider = bot.ai_provider.value
    if provider == "ollama":
        raise HTTPException(400, "Ollama no usa API key")
    key = (data.api_key or "").strip()
    if len(key) < 8 or len(key) > 512 or any(c.isspace() for c in key):
        raise HTTPException(400, "La API key no tiene un formato válido")
    try:
        await asyncio.wait_for(_fetch_live_models(provider, key), timeout=20)
    except Exception:
        # Sin detalle del error: podría reflejar la key. El log tampoco la incluye.
        logger.warning("bot_api_key_rejected", bot_id=bot_id, provider=provider, by=payload["sub"])
        raise HTTPException(400, f"{provider} rechazó la API key (o no se pudo verificar). Revisala e intentá de nuevo")
    bot.ai_api_key_encrypted = encrypt_secret(key)
    bot.ai_api_key_hint = key[-4:]
    bot.ai_api_key_updated_at = datetime.now(timezone.utc)
    bot.ai_api_key_updated_by = payload["sub"]
    await db.commit()
    logger.info("bot_api_key_set", bot_id=bot_id, provider=provider, by=payload["sub"], hint=key[-4:])
    return {"ok": True, "hint": key[-4:]}


@chatbots_router.delete("/{bot_id}/ai-key")
async def delete_bot_api_key(bot_id: str, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    bot = await _get_owned_chatbot(bot_id, payload, db)
    bot.ai_api_key_encrypted = bot.ai_api_key_hint = None
    bot.ai_api_key_updated_at, bot.ai_api_key_updated_by = datetime.now(timezone.utc), payload["sub"]
    await db.commit()
    logger.info("bot_api_key_deleted", bot_id=bot_id, by=payload["sub"])
    return {"ok": True}


@chatbots_router.delete("/{bot_id}")
async def delete_chatbot(bot_id: str, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    bot = await _get_owned_chatbot(bot_id, payload, db)
    await db.delete(bot)
    await db.commit()
    _delete_bot_image(bot_id, AVATARS_DIR)
    _delete_bot_image(bot_id, ORG_LOGOS_DIR)
    return {"ok": True}


# ─── Asignaciones (qué usuarios, además del dueño, tienen acceso a este bot) ───

class AssignmentCreate(BaseModel):
    user_id: str


@chatbots_router.get("/{bot_id}/assignments")
async def list_assignments(bot_id: str, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    await _get_owned_chatbot(bot_id, payload, db)
    result = await db.execute(
        select(User, ChatbotAssignment.id.label("assignment_id"))
        .join(ChatbotAssignment, ChatbotAssignment.user_id == User.id)
        .where(ChatbotAssignment.chatbot_id == bot_id)
        .order_by(User.username)
    )
    return [{"assignment_id": a_id, "user_id": u.id, "username": u.username,
             "email": u.email, "role": u.role.value} for u, a_id in result.all()]


@chatbots_router.post("/{bot_id}/assignments", status_code=201)
async def create_assignment(bot_id: str, data: AssignmentCreate, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    bot = await _get_owned_chatbot(bot_id, payload, db)
    user = await db.get(User, data.user_id)
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    if user.id == bot.owner_id:
        raise HTTPException(409, "Ese usuario ya es el dueño del bot")
    existing = await _is_assigned(bot_id, data.user_id, db)
    if existing:
        raise HTTPException(409, "Ese usuario ya tiene acceso a este bot")
    assignment = ChatbotAssignment(chatbot_id=bot_id, user_id=data.user_id)
    db.add(assignment)
    await db.commit()
    return {"ok": True}


@chatbots_router.delete("/{bot_id}/assignments/{user_id}")
async def delete_assignment(bot_id: str, user_id: str, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    await _get_owned_chatbot(bot_id, payload, db)
    result = await db.execute(
        select(ChatbotAssignment).where(ChatbotAssignment.chatbot_id == bot_id, ChatbotAssignment.user_id == user_id)
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(404, "Asignación no encontrada")
    await db.delete(assignment)
    await db.commit()
    return {"ok": True}


# ─── Avatar del bot (imagen usada en el widget y la página de chat) ───

AVATAR_EXT_BY_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
}
MAX_AVATAR_SIZE_BYTES = 2 * 1024 * 1024  # 2MB
AVATARS_DIR = os.path.join("static", "avatars")
ORG_LOGOS_DIR = os.path.join("static", "org_logos")


IMAGE_EXTS = ("png", "jpg", "gif", "webp", "svg")


def _sniff_image_ext(content: bytes) -> Optional[str]:
    """Detecta el tipo real de imagen por sus primeros bytes — no confía en el
    Content-Type declarado por el cliente (trivial de falsificar)."""
    for magic, ext in AVATAR_EXT_BY_MAGIC.items():
        if content.startswith(magic):
            return ext
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    # SVG es texto XML, no tiene bytes mágicos fijos — se detecta buscando la etiqueta <svg.
    # Servido siempre vía <img src="...">, el navegador nunca ejecuta <script> dentro de un SVG así.
    if b"<svg" in content[:1024].lower():
        return "svg"
    return None


def _image_paths(directory: str, base_name: str):
    return [os.path.join(directory, f"{base_name}.{ext}") for ext in IMAGE_EXTS]


def _avatar_paths(bot_id: str):
    return _image_paths(AVATARS_DIR, bot_id)


async def _upload_bot_image(bot_id: str, file: UploadFile, directory: str, url_prefix: str, payload: dict, db: AsyncSession) -> str:
    """Valida y guarda una imagen asociada a un bot (avatar u logo de organismo),
    con nombre fijo por bot_id (pisa la anterior, sin acumular basura)."""
    content = await file.read()
    if len(content) > MAX_AVATAR_SIZE_BYTES:
        raise HTTPException(413, "Imagen demasiado grande (máx 2MB)")
    ext = _sniff_image_ext(content)
    if not ext:
        raise HTTPException(400, "Formato de imagen no reconocido (usá PNG, JPG, GIF, WEBP o SVG)")

    os.makedirs(directory, exist_ok=True)
    for old_path in _image_paths(directory, bot_id):
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError as e:
                logger.warning("bot_image_delete_error", path=old_path, error=str(e))

    file_path = os.path.join(directory, f"{bot_id}.{ext}")
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)
    return f"{url_prefix}/{bot_id}.{ext}"


def _delete_bot_image(bot_id: str, directory: str) -> None:
    for path in _image_paths(directory, bot_id):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                logger.warning("bot_image_delete_error", path=path, error=str(e))


@chatbots_router.post("/{bot_id}/avatar")
async def upload_bot_avatar(bot_id: str, file: UploadFile = File(...), payload: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    bot = await _get_owned_chatbot(bot_id, payload, db)
    bot.bot_avatar_url = await _upload_bot_image(bot_id, file, AVATARS_DIR, "/static/avatars", payload, db)
    await db.commit()
    return {"avatar_url": bot.bot_avatar_url}


@chatbots_router.delete("/{bot_id}/avatar")
async def delete_bot_avatar(bot_id: str, payload: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    bot = await _get_owned_chatbot(bot_id, payload, db)
    _delete_bot_image(bot_id, AVATARS_DIR)
    bot.bot_avatar_url = None
    await db.commit()
    return {"ok": True}


@chatbots_router.post("/{bot_id}/org-logo")
async def upload_org_logo(bot_id: str, file: UploadFile = File(...), payload: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    bot = await _get_owned_chatbot(bot_id, payload, db)
    bot.org_logo_url = await _upload_bot_image(bot_id, file, ORG_LOGOS_DIR, "/static/org_logos", payload, db)
    await db.commit()
    return {"org_logo_url": bot.org_logo_url}


@chatbots_router.delete("/{bot_id}/org-logo")
async def delete_org_logo(bot_id: str, payload: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    bot = await _get_owned_chatbot(bot_id, payload, db)
    _delete_bot_image(bot_id, ORG_LOGOS_DIR)
    bot.org_logo_url = None
    await db.commit()
    return {"ok": True}


# ─── Marca institucional global (logo del Gobierno, igual en todos los bots) ───

branding_router = APIRouter(prefix="/admin/branding", tags=["branding"])
BRANDING_DIR = os.path.join("static", "branding")
GOV_LOGO_EXTS = IMAGE_EXTS

# Logos globales de marca (los sube el superadmin, iguales en todos los bots):
#   gov_logo    -> header (Gobierno de Salta)
#   footer_logo -> pie del chat (Modernización)


def _branding_logo_url(name: str) -> Optional[str]:
    for ext in GOV_LOGO_EXTS:
        if os.path.exists(os.path.join(BRANDING_DIR, f"{name}.{ext}")):
            return f"/static/branding/{name}.{ext}"
    return None


def _gov_logo_url() -> Optional[str]:
    return _branding_logo_url("gov_logo")


def _footer_logo_url() -> Optional[str]:
    return _branding_logo_url("footer_logo")


def _remove_branding_logo(name: str) -> None:
    for ext in GOV_LOGO_EXTS:
        path = os.path.join(BRANDING_DIR, f"{name}.{ext}")
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                logger.warning("branding_logo_delete_error", path=path, error=str(e))


async def _save_branding_logo(name: str, file: UploadFile) -> str:
    content = await file.read()
    if len(content) > MAX_AVATAR_SIZE_BYTES:
        raise HTTPException(413, "Imagen demasiado grande (máx 2MB)")
    ext = _sniff_image_ext(content)
    if not ext:
        raise HTTPException(400, "Formato de imagen no reconocido (usá PNG, JPG, GIF, WEBP o SVG)")
    os.makedirs(BRANDING_DIR, exist_ok=True)
    _remove_branding_logo(name)
    async with aiofiles.open(os.path.join(BRANDING_DIR, f"{name}.{ext}"), "wb") as f:
        await f.write(content)
    return f"/static/branding/{name}.{ext}"


@branding_router.get("/")
async def get_branding():
    """Público: la página de chat y el widget lo necesitan sin login."""
    return {"gov_logo_url": _gov_logo_url(), "footer_logo_url": _footer_logo_url()}


@branding_router.post("/gov-logo")
async def upload_gov_logo(file: UploadFile = File(...), payload: dict = Depends(require_role("superadmin"))):
    return {"gov_logo_url": await _save_branding_logo("gov_logo", file)}


@branding_router.delete("/gov-logo")
async def delete_gov_logo(payload: dict = Depends(require_role("superadmin"))):
    _remove_branding_logo("gov_logo")
    return {"ok": True}


@branding_router.post("/footer-logo")
async def upload_footer_logo(file: UploadFile = File(...), payload: dict = Depends(require_role("superadmin"))):
    return {"footer_logo_url": await _save_branding_logo("footer_logo", file)}


@branding_router.delete("/footer-logo")
async def delete_footer_logo(payload: dict = Depends(require_role("superadmin"))):
    _remove_branding_logo("footer_logo")
    return {"ok": True}


@chatbots_router.get("/{bot_id}/widget.js")
async def get_widget_script(bot_id: str, request: Request, key: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    bot = await db.get(Chatbot, bot_id)
    if not bot or not bot.is_active or not bot.is_public:
        raise HTTPException(404, "Bot no disponible")
    widget_config = bot.widget_config or {}
    # json.dumps escapa comillas, backslashes y </script — evita romper el contexto JS
    # con datos configurados por el admin del bot (bot_name, welcome_message, etc.)
    config_json = json.dumps({
        "botId": bot_id,
        "botName": bot.bot_name,
        "botAvatar": bot.bot_avatar_url,  # emoji o path "/static/avatars/..." (relativo a apiUrl)
        "govLogoUrl": _gov_logo_url(),  # path "/static/branding/..." (relativo a apiUrl) o null
        "footerLogoUrl": _footer_logo_url(),  # logo de Modernización (pie del chat), idem
        "orgLogoUrl": bot.org_logo_url,  # logo del organismo/secretaría dueña de este bot
        "welcomeMessage": bot.welcome_message,
        "primaryColor": widget_config.get("primary_color", "#6c63ff"),
        "secondaryColor": widget_config.get("secondary_color", "#a78bfa"),
        "position": widget_config.get("position", "bottom-right"),
        "apiKey": key,  # si el bot tiene API keys activas, esta se manda como X-API-Key en cada mensaje
    }).replace("</", "<\\/")
    api_url_json = json.dumps(_public_api_url(request, widget_config.get("api_url"))).replace("</", "<\\/")
    script = f"""(function(){{
  var config = {config_json};
  config.apiUrl = window.RAGBOT_API_URL || {api_url_json};
  var s = document.createElement('script');
  s.src = config.apiUrl + '/static/widget.js';
  s.onload = function(){{ window.RAGBot.init(config); }};
  document.head.appendChild(s);
}})();"""
    from fastapi.responses import Response
    return Response(content=script, media_type="application/javascript")


# ═══════════════════════════════════════════════════════════════
# API KEYS — restringen el chat público por origen/dominio (opcional)
# ═══════════════════════════════════════════════════════════════

api_keys_router = APIRouter(prefix="/chatbots/{bot_id}/api-keys", tags=["api-keys"])


@api_keys_router.get("/")
async def list_api_keys(bot_id: str, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    await _get_owned_chatbot(bot_id, payload, db)
    result = await db.execute(select(APIKey).where(APIKey.chatbot_id == bot_id).order_by(APIKey.created_at.desc()))
    keys = result.scalars().all()
    return [{"id": k.id, "name": k.name, "allowed_origins": k.allowed_origins or [],
             "is_active": k.is_active, "requests_count": k.requests_count,
             "last_used": k.last_used.isoformat() if k.last_used else None,
             "created_at": k.created_at.isoformat()} for k in keys]


@api_keys_router.post("/", status_code=201)
async def create_api_key(bot_id: str, data: APIKeyCreate, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    await _get_owned_chatbot(bot_id, payload, db)
    raw_key = f"rbk_{secrets.token_urlsafe(32)}"
    key = APIKey(chatbot_id=bot_id, key_hash=_hash_api_key(raw_key), name=data.name,
                 allowed_origins=data.allowed_origins or None)
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return {"id": key.id, "name": key.name, "allowed_origins": key.allowed_origins or [],
            "api_key": raw_key}  # única vez que se devuelve el valor en texto plano


@api_keys_router.patch("/{key_id}")
async def update_api_key(bot_id: str, key_id: str, data: APIKeyUpdate, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    await _get_owned_chatbot(bot_id, payload, db)
    key = await db.get(APIKey, key_id)
    if not key or key.chatbot_id != bot_id:
        raise HTTPException(404, "API key no encontrada")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(key, k, v)
    await db.commit()
    return {"ok": True}


@api_keys_router.delete("/{key_id}")
async def delete_api_key(bot_id: str, key_id: str, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    await _get_owned_chatbot(bot_id, payload, db)
    key = await db.get(APIKey, key_id)
    if not key or key.chatbot_id != bot_id:
        raise HTTPException(404, "API key no encontrada")
    await db.delete(key)
    await db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# AI PROVIDERS — API keys globales por proveedor + caché de modelos
# ═══════════════════════════════════════════════════════════════

ai_providers_router = APIRouter(prefix="/admin/ai-providers", tags=["ai-providers"])

# Fallback curado: se usa si nunca se hizo un "actualizar modelos" (o si falla)
CURATED_MODELS = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307", "claude-3-opus-20240229"],
    "google": ["gemini-2.5-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"],
    "ollama": ["llama3", "llama3:70b", "mistral", "mixtral", "codellama"],
}

_ENV_API_KEYS = {
    "openai": lambda: settings.OPENAI_API_KEY,
    "anthropic": lambda: settings.ANTHROPIC_API_KEY,
    "google": lambda: settings.GOOGLE_API_KEY,
}


class ProviderConfigUpdate(BaseModel):
    api_key: Optional[str] = None   # "" para borrar la key guardada y volver a usar la de .env
    base_url: Optional[str] = None  # usado por Ollama


async def _get_provider_config(provider: str, db: AsyncSession) -> Optional[AIProviderConfig]:
    result = await db.execute(select(AIProviderConfig).where(AIProviderConfig.provider == provider))
    return result.scalar_one_or_none()


async def _get_or_create_provider_config(provider: str, db: AsyncSession) -> AIProviderConfig:
    cfg = await _get_provider_config(provider, db)
    if not cfg:
        cfg = AIProviderConfig(provider=provider)
        db.add(cfg)
        await db.flush()
    return cfg


def _resolve_provider_key(provider: str, cfg: Optional[AIProviderConfig]) -> str:
    if cfg and cfg.api_key_encrypted:
        return decrypt_secret(cfg.api_key_encrypted)
    getter = _ENV_API_KEYS.get(provider)
    return getter() if getter else ""


async def _fetch_live_models(provider: str, api_key: str, base_url: Optional[str] = None) -> List[str]:
    if provider == "openai":
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.models.list()
        return sorted({m.id for m in resp.data if "gpt" in m.id or m.id.startswith(("o1", "o3", "o4"))})

    if provider == "anthropic":
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            )
            resp.raise_for_status()
            data = resp.json()
        return [m["id"] for m in data.get("data", [])]

    if provider == "google":
        import httpx
        models, page_token = [], None
        async with httpx.AsyncClient(timeout=15) as client:
            for _ in range(10):  # paginado
                resp = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    headers={"x-goog-api-key": api_key},
                    params={"pageSize": 100, **({"pageToken": page_token} if page_token else {})},
                )
                resp.raise_for_status()
                data = resp.json()
                models += [
                    m["name"].replace("models/", "")
                    for m in data.get("models", [])
                    if "generateContent" in m.get("supportedGenerationMethods", [])
                ]
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return sorted(set(models))

    if provider == "ollama":
        import httpx
        url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        return [m["name"] for m in data.get("models", [])]

    raise ValueError(f"Proveedor desconocido: {provider}")


@ai_providers_router.get("/")
async def list_ai_providers(payload: dict = Depends(require_role("superadmin")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AIProviderConfig))
    configs = {c.provider.value: c for c in result.scalars().all()}
    out = []
    for provider in CURATED_MODELS:
        cfg = configs.get(provider)
        has_db_key = bool(cfg and cfg.api_key_encrypted)
        has_env_key = bool(_ENV_API_KEYS.get(provider, lambda: "")())
        out.append({
            "provider": provider,
            "configured": has_db_key or has_env_key or provider == "ollama",
            "key_source": "db" if has_db_key else ("env" if has_env_key else None),
            "base_url": (cfg.base_url if cfg else None) or (settings.OLLAMA_BASE_URL if provider == "ollama" else None),
            "models": (cfg.models if cfg and cfg.models else None) or CURATED_MODELS[provider],
            "models_source": "cached" if (cfg and cfg.models) else "curated",
            "models_updated_at": cfg.models_updated_at.isoformat() if cfg and cfg.models_updated_at else None,
        })
    return out


@ai_providers_router.put("/{provider}")
async def update_ai_provider(provider: str, data: ProviderConfigUpdate, payload: dict = Depends(require_role("superadmin")), db: AsyncSession = Depends(get_db)):
    if provider not in CURATED_MODELS:
        raise HTTPException(404, "Proveedor desconocido")
    cfg = await _get_or_create_provider_config(provider, db)
    if data.api_key is not None:
        cfg.api_key_encrypted = encrypt_secret(data.api_key) if data.api_key else None
    if data.base_url is not None:
        cfg.base_url = data.base_url or None
    await db.commit()
    return {"ok": True}


@ai_providers_router.post("/{provider}/refresh-models")
async def refresh_provider_models(provider: str, payload: dict = Depends(require_role("superadmin")), db: AsyncSession = Depends(get_db)):
    if provider not in CURATED_MODELS:
        raise HTTPException(404, "Proveedor desconocido")
    cfg = await _get_or_create_provider_config(provider, db)
    api_key = _resolve_provider_key(provider, cfg)
    if provider != "ollama" and not api_key:
        raise HTTPException(400, "Configurá una API key para este proveedor antes de actualizar los modelos")
    try:
        models = await _fetch_live_models(provider, api_key, cfg.base_url)
    except Exception as e:
        logger.warning("ai_provider_refresh_failed", provider=provider, error=str(e))
        raise HTTPException(502, f"No se pudo consultar el proveedor: {e}")
    if not models:
        raise HTTPException(502, "El proveedor no devolvió ningún modelo")
    cfg.models = models
    cfg.models_updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"provider": provider, "models": models, "models_updated_at": cfg.models_updated_at.isoformat()}


@ai_providers_router.get("/{provider}/models")
async def get_provider_models(provider: str, payload: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    if provider not in CURATED_MODELS:
        raise HTTPException(404, "Proveedor desconocido")
    cfg = await _get_provider_config(provider, db)
    models = (cfg.models if cfg and cfg.models else None) or CURATED_MODELS[provider]
    return {"provider": provider, "models": models, "source": "cached" if (cfg and cfg.models) else "curated"}


# ═══════════════════════════════════════════════════════════════
# DOCUMENTS
# ═══════════════════════════════════════════════════════════════

documents_router = APIRouter(prefix="/chatbots/{bot_id}/documents", tags=["documents"])

ALLOWED_MIMES = {
    "application/pdf", "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@documents_router.get("/")
async def list_documents(bot_id: str, payload: dict = Depends(get_current_user_payload), db: AsyncSession = Depends(get_db)):
    await _get_owned_chatbot(bot_id, payload, db)
    result = await db.execute(select(Document).where(Document.chatbot_id == bot_id).order_by(Document.created_at.desc()))
    docs = result.scalars().all()
    return [{"id": d.id, "filename": d.original_filename, "status": d.status.value,
             "chunk_count": d.chunk_count, "page_count": d.page_count,
             "file_size": d.file_size, "created_at": d.created_at.isoformat(),
             "error_message": d.error_message} for d in docs]


def _safe_filename(name: str) -> str:
    """Aísla solo el nombre de archivo, sin componentes de ruta (evita path traversal)."""
    name = os.path.basename((name or "").replace("\\", "_")).lstrip(".")
    return name or "documento"


@documents_router.post("/", status_code=202)
async def upload_document(
    bot_id: str, background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    payload: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_chatbot(bot_id, payload, db)
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, f"Tipo no permitido: {file.content_type}")
    content = await file.read()
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(413, f"Archivo demasiado grande (máx {settings.MAX_FILE_SIZE_MB}MB)")
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    upload_dir_abs = os.path.abspath(settings.UPLOAD_DIR)
    safe_name = f"{uuid.uuid4()}_{_safe_filename(file.filename)}"
    file_path = os.path.join(settings.UPLOAD_DIR, safe_name)
    if os.path.dirname(os.path.abspath(file_path)) != upload_dir_abs:
        raise HTTPException(400, "Nombre de archivo inválido")
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)
    doc = Document(chatbot_id=bot_id, filename=safe_name,
                   original_filename=file.filename, file_path=file_path,
                   file_size=len(content), mime_type=file.content_type,
                   uploaded_by=payload["sub"])
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    background_tasks.add_task(_process_doc_background, doc.id)
    return {"id": doc.id, "filename": file.filename, "status": "pending",
            "message": "Procesando en background"}


async def _process_doc_background(document_id: str):
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        rag = RAGService(db)
        await rag.process_document(document_id)


@documents_router.delete("/{doc_id}")
async def delete_document(bot_id: str, doc_id: str, payload: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    await _get_owned_chatbot(bot_id, payload, db)
    doc = await db.get(Document, doc_id)
    if not doc or doc.chatbot_id != bot_id:
        raise HTTPException(404, "Documento no encontrado")
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
    if os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except OSError as e:
            logger.warning("file_delete_error", path=doc.file_path, error=str(e))
    await db.delete(doc)
    await db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# CHAT — GET sirve HTML, POST procesa mensaje
# ═══════════════════════════════════════════════════════════════

chat_router = APIRouter(prefix="/chat", tags=["chat"])

# HTML del chat embebido — se genera dinámicamente para no depender de archivos externos
CHAT_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{bot_name}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f8f8fc;
         height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
  :root {{ --color: {primary_color}; --color2: {secondary_color}; }}
  .header {{ background: linear-gradient(135deg, var(--color), var(--color2)); color: #fff; padding: 14px 20px;
             display: flex; align-items: center; gap: 12px; flex-shrink: 0; }}
  .gov-logo {{ height: 30px; width: auto; border-radius: 4px; flex-shrink: 0; }}
  .org-logo {{ height: 30px; width: auto; border-radius: 4px; flex-shrink: 0; }}
  .avatar {{ width: 38px; height: 38px; border-radius: 50%;
             background: rgba(255,255,255,0.2);
             display: flex; align-items: center; justify-content: center; font-size: 20px; }}
  .header-info h1 {{ font-size: 15px; font-weight: 600; }}
  .header-info p {{ font-size: 12px; opacity: 0.75; }}
  .messages {{ flex: 1; overflow-y: auto; padding: 20px;
               display: flex; flex-direction: column; gap: 14px; }}
  .messages::-webkit-scrollbar {{ width: 5px; }}
  .messages::-webkit-scrollbar-thumb {{ background: #ddd; border-radius: 3px; }}
  .msg {{ display: flex; gap: 10px; align-items: flex-end; }}
  .msg.user {{ flex-direction: row-reverse; }}
  .msg-av {{ width: 30px; height: 30px; border-radius: 50%; background: var(--color);
             display: flex; align-items: center; justify-content: center;
             font-size: 14px; color: #fff; flex-shrink: 0; }}
  .msg.user .msg-av {{ background: #e8e8f5; color: #555; }}
  .bubble {{ max-width: 72%; padding: 11px 15px; border-radius: 18px;
             font-size: 14px; line-height: 1.5; }}
  .msg.bot .bubble {{ background: {bot_bubble_color}; border-bottom-left-radius: 4px; color: #1a1a2e;
                      box-shadow: 0 1px 4px rgba(0,0,0,0.07); }}
  .msg.user .bubble {{ background: var(--color); color: #fff; border-bottom-right-radius: 4px; }}
  .sources {{ margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }}
  .src {{ background: #f0f0f8; color: #666; font-size: 11px; padding: 3px 10px; border-radius: 20px; }}
  .msg-time {{ font-size: 10px; color: #bbb; margin-top: 3px; }}
  .typing {{ display: flex; align-items: center; gap: 4px; padding: 12px 15px;
             background: #fff; border-radius: 18px; border-bottom-left-radius: 4px;
             width: fit-content; box-shadow: 0 1px 4px rgba(0,0,0,0.07); }}
  .typing span {{ width: 7px; height: 7px; background: #bbb; border-radius: 50%;
                  animation: dot 1.4s infinite; }}
  .typing span:nth-child(2) {{ animation-delay: 0.2s; }}
  .typing span:nth-child(3) {{ animation-delay: 0.4s; }}
  @keyframes dot {{ 0%,80%,100% {{ transform:scale(0.6); opacity:0.4; }}
                    40% {{ transform:scale(1); opacity:1; }} }}
  .input-area {{ background: #fff; border-top: 1px solid #eee;
                 padding: 14px 20px; display: flex; gap: 10px; align-items: flex-end;
                 flex-shrink: 0; }}
  #inp {{ flex:1; border: 1.5px solid #e8e8f0; border-radius: 22px;
          padding: 10px 16px; font-size: 14px; outline: none; resize: none;
          font-family: inherit; max-height: 110px; line-height: 1.4;
          transition: border-color 0.15s; }}
  #inp:focus {{ border-color: var(--color); }}
  #send {{ width: 42px; height: 42px; border-radius: 50%; background: var(--color);
           border: none; cursor: pointer; display: flex; align-items: center;
           justify-content: center; transition: filter 0.15s, transform 0.15s;
           flex-shrink: 0; }}
  #send:hover {{ filter: brightness(1.1); transform: scale(1.05); }}
  #send svg {{ width: 16px; height: 16px; }}
  /* El logo de Modernización es blanco: va sobre el mismo degradé del header */
  .footer-logo {{ background: linear-gradient(135deg, var(--color), var(--color2)); padding: 10px 16px;
                  display: flex; justify-content: center; align-items: center; flex-shrink: 0; }}
  .footer-logo img {{ max-height: 28px; max-width: 75%; width: auto; object-fit: contain; display: block; }}
</style>
</head>
<body>
<div class="header">
  {gov_logo_html}
  {org_logo_html}
  <div class="avatar">{avatar}</div>
  <div class="header-info">
    <h1>{bot_name}</h1>
    <p>● En línea</p>
  </div>
</div>
<div class="messages" id="msgs"></div>
<div class="input-area">
  <textarea id="inp" placeholder="Escribe tu mensaje..." rows="1" maxlength="2000"></textarea>
  <button id="send">
    <svg fill="none" stroke="#fff" stroke-width="2" viewBox="0 0 24 24">
      <line x1="22" y1="2" x2="11" y2="13"></line>
      <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
    </svg>
  </button>
</div>
{footer_logo_html}
<script>
const API = {api_url_js};
const BOT_ID = {bot_id_js};
const API_KEY = {api_key_js};
const SESSION = "pg_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
let busy = false;

function esc(s) {{
  return String(s ?? "").replace(/[&<>"']/g, c => (
    {{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]
  ));
}}

function addMsg(role, content, sources) {{
  const m = document.getElementById("msgs");
  const time = new Date().toLocaleTimeString("es", {{hour:"2-digit",minute:"2-digit"}});
  const srcs = (sources||[]).map(s=>`<span class="src">📎 ${{esc(s)}}</span>`).join("");
  const d = document.createElement("div");
  d.className = "msg " + role;
  d.innerHTML = `<div class="msg-av">${{role==="bot"?"{avatar_js}":"👤"}}</div>
    <div><div class="bubble">${{esc(content).replace(/\\n/g,"<br>")}}${{srcs?`<div class="sources">${{srcs}}</div>`:""}}</div>
    <div class="msg-time">${{time}}</div></div>`;
  m.appendChild(d);
  m.scrollTop = m.scrollHeight;
}}

// Mensaje de bienvenida
addMsg("bot", {welcome_message_js});

async function send() {{
  const inp = document.getElementById("inp");
  const txt = inp.value.trim();
  if (!txt || busy) return;
  inp.value = ""; inp.style.height = "auto";
  addMsg("user", txt);
  // Typing indicator
  const m = document.getElementById("msgs");
  const t = document.createElement("div");
  t.id = "typing"; t.className = "msg bot";
  t.innerHTML = `<div class="msg-av">{avatar_js}</div><div class="typing"><span></span><span></span><span></span></div>`;
  m.appendChild(t); m.scrollTop = m.scrollHeight;
  busy = true;
  try {{
    const headers = {{"Content-Type": "application/json"}};
    if (API_KEY) headers["X-API-Key"] = API_KEY;
    const res = await fetch(`${{API}}/api/v1/chat/${{BOT_ID}}`, {{
      method: "POST", headers,
      body: JSON.stringify({{message: txt, session_id: SESSION}})
    }});
    const data = await res.json();
    document.getElementById("typing")?.remove();
    if (!res.ok) throw new Error(data.detail || "Error");
    addMsg("bot", data.answer, data.sources);
  }} catch(e) {{
    document.getElementById("typing")?.remove();
    addMsg("bot", "Error al procesar tu consulta: " + e.message);
  }} finally {{ busy = false; }}
}}

document.getElementById("send").addEventListener("click", send);
document.getElementById("inp").addEventListener("keydown", e => {{
  if (e.key === "Enter" && !e.shiftKey) {{ e.preventDefault(); send(); }}
}});
document.getElementById("inp").addEventListener("input", function() {{
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 110) + "px";
}});
</script>
</body>
</html>"""


def _tint_hex(hex_color: str, amount: float = 0.85) -> str:
    """Mezcla un color hex con blanco (amount=1 -> blanco puro) para un tono pastel
    siempre legible con texto oscuro, sin importar cuán saturado sea el color original."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return "#f5f5f8"
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return "#f5f5f8"
    mix = lambda c: round(c + (255 - c) * amount)
    return f"#{mix(r):02x}{mix(g):02x}{mix(b):02x}"


def _public_api_url(request: Request, configured: Optional[str] = None) -> str:
    """URL base del API para el navegador: la del bot (widget_config.api_url), si no
    PUBLIC_API_URL, y como último recurso el origen de la request (nunca un localhost fijo)."""
    url = configured or settings.PUBLIC_API_URL or str(request.base_url)
    return url.rstrip("/")


def _avatar_html(avatar_value: str, api_url: str) -> str:
    """HTML seguro para el avatar: <img> si es una URL/path de imagen subida, o el
    emoji/texto escapado si no. Nunca vuelca el valor crudo sin escapar."""
    if avatar_value.startswith(("http://", "https://")):
        src = avatar_value
    elif avatar_value.startswith("/"):
        src = api_url.rstrip("/") + avatar_value
    else:
        return html.escape(avatar_value)
    return f'<img src="{html.escape(src)}" style="width:100%;height:100%;border-radius:50%;object-fit:cover;display:block">'


@chat_router.get("/{bot_id}", response_class=HTMLResponse)
async def chat_page(bot_id: str, request: Request, key: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """Sirve la página HTML del chat — usada por iframe y 'Abrir en nueva pestaña'."""
    bot = await db.get(Chatbot, bot_id)
    if not bot or not bot.is_active or not bot.is_public:
        raise HTTPException(404, "Bot no encontrado o inactivo")

    config = bot.widget_config or {}
    primary_color = config.get("primary_color", "#6c63ff")
    if not re.fullmatch(r"#[0-9a-fA-F]{3,8}", primary_color or ""):
        primary_color = "#6c63ff"  # valor libre en config solo se usa dentro de <style>; validar como color
    secondary_color = config.get("secondary_color", "#a78bfa")
    if not re.fullmatch(r"#[0-9a-fA-F]{3,8}", secondary_color or ""):
        secondary_color = "#a78bfa"
    bot_bubble_color = _tint_hex(secondary_color, 0.85)
    avatar = bot.bot_avatar_url or "🤖"
    api_url = _public_api_url(request, config.get("api_url"))
    avatar_html = _avatar_html(avatar, api_url)
    gov_logo_url = _gov_logo_url()
    gov_logo_html = (
        f'<img class="gov-logo" src="{html.escape(api_url.rstrip("/") + gov_logo_url)}" alt="Gobierno de Salta">'
        if gov_logo_url else ""
    )
    footer_logo_url = _footer_logo_url()
    footer_logo_html = (
        f'<div class="footer-logo"><img src="{html.escape(api_url.rstrip("/") + footer_logo_url)}" alt="Modernización"></div>'
        if footer_logo_url else ""
    )
    org_logo_html = ""
    if bot.org_logo_url:
        org_src = bot.org_logo_url
        if org_src.startswith("/"):
            org_src = api_url.rstrip("/") + org_src
        org_logo_html = f'<img class="org-logo" src="{html.escape(org_src)}" alt="Logo del organismo">'

    def js_str(value: str) -> str:
        # Literal JS seguro (comillas incluidas): escapa comillas/backslashes y evita </script>
        return json.dumps(value).replace("</", "<\\/")

    page_html = CHAT_PAGE_TEMPLATE.format(
        bot_id=bot_id,
        bot_id_js=js_str(bot_id),
        bot_name=html.escape(bot.bot_name or bot.name),
        welcome_message_js=js_str(bot.welcome_message or "¡Hola! ¿En qué puedo ayudarte?"),
        primary_color=primary_color,
        secondary_color=secondary_color,
        bot_bubble_color=bot_bubble_color,
        avatar=avatar_html,  # ya es HTML seguro (img escapado o texto escapado), no volver a escapar
        gov_logo_html=gov_logo_html,
        footer_logo_html=footer_logo_html,
        org_logo_html=org_logo_html,
        avatar_js=js_str(avatar_html)[1:-1],  # sin comillas: se inserta dentro de un template literal ya entrecomillado
        api_url_js=js_str(api_url),
        api_key_js=js_str(key) if key else "null",
    )
    return HTMLResponse(content=page_html)


async def _authorize_public_chat(bot_id: str, request: Request, db: AsyncSession) -> None:
    """Si el bot tiene API keys activas configuradas, exige una válida en X-API-Key (y su
    allowed_origins si tiene alguno definido). Si no tiene ninguna key activa, deja el chat
    abierto como hasta ahora — así los bots ya embebidos sin este control no se rompen."""
    result = await db.execute(select(APIKey).where(APIKey.chatbot_id == bot_id, APIKey.is_active == True))
    keys = result.scalars().all()
    if not keys:
        return

    provided = request.headers.get("x-api-key")
    if not provided:
        raise HTTPException(401, "Este chatbot requiere una API key (header X-API-Key)")

    provided_hash = _hash_api_key(provided)
    matched = next((k for k in keys if k.key_hash == provided_hash), None)
    if not matched:
        raise HTTPException(401, "API key inválida")

    if matched.allowed_origins:
        origin = request.headers.get("origin")
        if not origin or origin not in matched.allowed_origins:
            raise HTTPException(403, "Origen no permitido para esta API key")

    matched.last_used = datetime.now(timezone.utc)
    matched.requests_count = (matched.requests_count or 0) + 1
    await db.commit()


@chat_router.post("/{bot_id}")
async def chat_api(
    bot_id: str,
    data: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Endpoint POST de la API de chat."""
    await _authorize_public_chat(bot_id, request, db)
    svc = ChatService(db)
    try:
        result = await svc.chat(
            chatbot_id=bot_id,
            session_id=data.session_id,
            user_message=data.message,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        return result
    except BotUnavailable as e:
        # Sin key propia o sin cupo: el usuario final ve un mensaje genérico; el motivo real queda en el log
        logger.warning("bot_unavailable", bot_id=bot_id, reason=str(e))
        if e.public_message == MSG_UNAVAILABLE:  # el aviso del límite ya lo maneja record_usage (80%/100%)
            asyncio.create_task(notify_bot_event(bot_id, "no-api-key", f"Bot {bot_id} sin API key propia", str(e)))
        raise HTTPException(503, e.public_message)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("chat_error", error=scrub_secrets(str(e)))
        asyncio.create_task(notify_bot_failure(bot_id, e))
        raise HTTPException(500, "Error interno del servidor")


# ═══════════════════════════════════════════════════════════════
# ANALYTICS
# ═══════════════════════════════════════════════════════════════

analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])


@analytics_router.get("/dashboard")
async def dashboard_stats(payload: dict = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)):
    # Admin/superadmin: totales globales. El resto: solo los bots que puede ver (dueño o asignado).
    visible = _visible_bot_ids(payload)

    def scoped(query, bot_id_col):
        return query if visible is None else query.where(bot_id_col.in_(visible))

    bots_count = await db.scalar(scoped(select(func.count(Chatbot.id)), Chatbot.id))
    docs_count = await db.scalar(scoped(
        select(func.count(Document.id)).where(Document.status == DocumentStatus.ready), Document.chatbot_id))
    convs_count = await db.scalar(scoped(select(func.count(Conversation.id)), Conversation.chatbot_id))
    msgs_count = await db.scalar(scoped(
        select(func.count(Message.id)).join(Conversation, Message.conversation_id == Conversation.id),
        Conversation.chatbot_id))
    total_tokens = await db.scalar(scoped(select(func.sum(Chatbot.total_tokens_used)), Chatbot.id)) or 0
    return {"chatbots": bots_count, "documents_ready": docs_count,
            "conversations": convs_count, "messages": msgs_count,
            "total_tokens_used": total_tokens}


@analytics_router.get("/conversations/{bot_id}")
async def bot_conversations(bot_id: str, limit: int = 50, payload: dict = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)):
    await _get_owned_chatbot(bot_id, payload, db)
    result = await db.execute(
        select(Conversation).where(Conversation.chatbot_id == bot_id)
        .order_by(Conversation.started_at.desc()).limit(limit)
    )
    convs = result.scalars().all()
    return [{"id": c.id, "session_id": c.session_id,
             "total_messages": c.total_messages, "total_tokens": c.total_tokens,
             "started_at": c.started_at.isoformat(),
             "last_activity": c.last_activity.isoformat()} for c in convs]


@analytics_router.get("/conversations/{conv_id}/messages")
async def conversation_messages(conv_id: str, payload: dict = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)):
    conv = await db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(404, "Conversación no encontrada")
    await _get_owned_chatbot(conv.chatbot_id, payload, db)
    result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    msgs = result.scalars().all()
    return [{"id": m.id, "role": m.role.value, "content": m.content,
             "model_used": m.model_used, "total_tokens": m.total_tokens,
             "latency_ms": m.latency_ms, "created_at": m.created_at.isoformat()} for m in msgs]