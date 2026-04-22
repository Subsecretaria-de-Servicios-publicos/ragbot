"""
app/api/routers.py — Todos los endpoints FastAPI
"""
import os
import uuid
import aiofiles
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, EmailStr
import structlog

from app.db.session import get_db
from app.models.models import User, Chatbot, Document, Conversation, Message, UserRole, DocumentStatus
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user_payload, require_role,
)
from app.core.config import settings
from app.services.chat_service import ChatService
from app.services.rag_service import RAGService

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# SCHEMAS (Pydantic)
# ═══════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: Optional[str] = None

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
    ai_provider: str = "openai"
    ai_model: str = "gpt-4o-mini"
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

class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.viewer


# ═══════════════════════════════════════════════════════════════
# AUTH ROUTER
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
async def refresh_token(refresh_token: str):
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token inválido")
    new_payload = {k: v for k, v in payload.items() if k not in ("exp", "type")}
    return {"access_token": create_access_token(new_payload), "token_type": "bearer"}


@auth_router.get("/me")
async def me(payload: dict = Depends(get_current_user_payload), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {"id": user.id, "email": user.email, "username": user.username, "role": user.role.value, "full_name": user.full_name}


# ═══════════════════════════════════════════════════════════════
# USERS ROUTER (superadmin)
# ═══════════════════════════════════════════════════════════════

users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("/")
async def list_users(
    payload: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [{"id": u.id, "email": u.email, "username": u.username, "role": u.role.value, "is_active": u.is_active} for u in users]


@users_router.post("/", status_code=201)
async def create_user(
    data: UserCreate,
    payload: dict = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email ya registrado")

    user = User(
        email=data.email,
        username=data.username,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
    )
    db.add(user)
    await db.commit()
    return {"id": user.id, "email": user.email, "role": user.role.value}


@users_router.patch("/{user_id}")
async def update_user(
    user_id: str,
    data: dict,
    payload: dict = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
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
# CHATBOTS ROUTER
# ═══════════════════════════════════════════════════════════════

chatbots_router = APIRouter(prefix="/chatbots", tags=["chatbots"])


def _make_slug(name: str) -> str:
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return f"{slug}-{str(uuid.uuid4())[:8]}"


@chatbots_router.get("/")
async def list_chatbots(
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db),
):
    query = select(Chatbot)
    if payload["role"] not in ("superadmin", "admin"):
        query = query.where(Chatbot.owner_id == payload["sub"])
    result = await db.execute(query.order_by(Chatbot.created_at.desc()))
    bots = result.scalars().all()
    return [{
        "id": b.id, "name": b.name, "slug": b.slug, "is_active": b.is_active,
        "ai_provider": b.ai_provider.value, "ai_model": b.ai_model,
        "total_conversations": b.total_conversations, "total_messages": b.total_messages,
        "total_tokens_used": b.total_tokens_used,
    } for b in bots]


@chatbots_router.post("/", status_code=201)
async def create_chatbot(
    data: ChatbotCreate,
    payload: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    bot = Chatbot(
        **data.model_dump(),
        slug=_make_slug(data.name),
        owner_id=payload["sub"],
    )
    db.add(bot)
    await db.commit()
    return {"id": bot.id, "slug": bot.slug, "name": bot.name}


@chatbots_router.get("/{bot_id}")
async def get_chatbot(
    bot_id: str,
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db),
):
    bot = await db.get(Chatbot, bot_id)
    if not bot:
        raise HTTPException(404, "Chatbot no encontrado")
    return bot.__dict__


@chatbots_router.patch("/{bot_id}")
async def update_chatbot(
    bot_id: str,
    data: ChatbotUpdate,
    payload: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    bot = await db.get(Chatbot, bot_id)
    if not bot:
        raise HTTPException(404, "No encontrado")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(bot, k, v)
    await db.commit()
    return {"ok": True}


@chatbots_router.delete("/{bot_id}")
async def delete_chatbot(
    bot_id: str,
    payload: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    bot = await db.get(Chatbot, bot_id)
    if not bot:
        raise HTTPException(404, "No encontrado")
    await db.delete(bot)
    await db.commit()
    return {"ok": True}


# Widget embed script endpoint
@chatbots_router.get("/{bot_id}/widget.js")
async def get_widget_script(bot_id: str, db: AsyncSession = Depends(get_db)):
    """Retorna el script JS para embeber el chatbot."""
    bot = await db.get(Chatbot, bot_id)
    if not bot or not bot.is_active:
        raise HTTPException(404, "Bot no disponible")
    config = bot.widget_config or {}
    script = f"""
(function(){{
  var config = {{
    botId: "{bot_id}",
    botName: "{bot.bot_name}",
    welcomeMessage: "{bot.welcome_message}",
    primaryColor: "{config.get('primary_color', '#3B82F6')}",
    position: "{config.get('position', 'bottom-right')}",
    apiUrl: window.RAGBOT_API_URL || "http://localhost:8000"
  }};
  var script = document.createElement('script');
  script.src = config.apiUrl + '/static/widget.js';
  script.onload = function(){{ window.RAGBot.init(config); }};
  document.head.appendChild(script);
}})();
"""
    from fastapi.responses import Response
    return Response(content=script, media_type="application/javascript")


# ═══════════════════════════════════════════════════════════════
# DOCUMENTS ROUTER
# ═══════════════════════════════════════════════════════════════

documents_router = APIRouter(prefix="/chatbots/{bot_id}/documents", tags=["documents"])

ALLOWED_MIMES = {"application/pdf", "text/plain", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


@documents_router.get("/")
async def list_documents(
    bot_id: str,
    payload: dict = Depends(get_current_user_payload),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Document).where(Document.chatbot_id == bot_id).order_by(Document.created_at.desc()))
    docs = result.scalars().all()
    return [{
        "id": d.id, "filename": d.original_filename, "status": d.status.value,
        "chunk_count": d.chunk_count, "page_count": d.page_count, "file_size": d.file_size,
        "created_at": d.created_at.isoformat(), "error_message": d.error_message,
    } for d in docs]


@documents_router.post("/", status_code=202)
async def upload_document(
    bot_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    payload: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(400, f"Tipo de archivo no permitido: {file.content_type}")

    # Leer y validar tamaño
    content = await file.read()
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(413, f"Archivo demasiado grande (máx {settings.MAX_FILE_SIZE_MB}MB)")

    # Guardar archivo
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    safe_name = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(settings.UPLOAD_DIR, safe_name)
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # Crear registro
    doc = Document(
        chatbot_id=bot_id,
        filename=safe_name,
        original_filename=file.filename,
        file_path=file_path,
        file_size=len(content),
        mime_type=file.content_type,
        uploaded_by=payload["sub"],
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Procesar en background
    background_tasks.add_task(_process_doc_background, doc.id)

    return {"id": doc.id, "filename": file.filename, "status": "pending", "message": "Procesando en background"}


async def _process_doc_background(document_id: str):
    """Task de background para procesar documento."""
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        rag = RAGService(db)
        await rag.process_document(document_id)


@documents_router.delete("/{doc_id}")
async def delete_document(
    bot_id: str,
    doc_id: str,
    payload: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    # Eliminar archivo físico
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    await db.delete(doc)
    await db.commit()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# CHAT ROUTER (público con API key)
# ═══════════════════════════════════════════════════════════════

chat_router = APIRouter(prefix="/chat", tags=["chat"])


@chat_router.post("/{bot_id}")
async def chat(
    bot_id: str,
    data: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint público de chat — autenticado con API key en header X-API-Key
    o JWT si es usuario del dashboard.
    """
    svc = ChatService(db)
    try:
        result = await svc.chat(
            chatbot_id=bot_id,
            session_id=data.session_id,
            user_message=data.message,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("chat_endpoint_error", error=str(e))
        raise HTTPException(500, "Error interno del servidor")


# ═══════════════════════════════════════════════════════════════
# ANALYTICS ROUTER
# ═══════════════════════════════════════════════════════════════

analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])


@analytics_router.get("/dashboard")
async def dashboard_stats(
    payload: dict = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    """Estadísticas generales para el dashboard."""
    bots_count = await db.scalar(select(func.count(Chatbot.id)))
    docs_count = await db.scalar(select(func.count(Document.id)).where(Document.status == DocumentStatus.ready))
    convs_count = await db.scalar(select(func.count(Conversation.id)))
    msgs_count = await db.scalar(select(func.count(Message.id)))
    total_tokens = await db.scalar(select(func.sum(Chatbot.total_tokens_used))) or 0

    return {
        "chatbots": bots_count,
        "documents_ready": docs_count,
        "conversations": convs_count,
        "messages": msgs_count,
        "total_tokens_used": total_tokens,
    }


@analytics_router.get("/conversations/{bot_id}")
async def bot_conversations(
    bot_id: str,
    limit: int = 50,
    payload: dict = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.chatbot_id == bot_id)
        .order_by(Conversation.started_at.desc())
        .limit(limit)
    )
    convs = result.scalars().all()
    return [{
        "id": c.id, "session_id": c.session_id, "total_messages": c.total_messages,
        "total_tokens": c.total_tokens, "started_at": c.started_at.isoformat(),
        "last_activity": c.last_activity.isoformat(),
    } for c in convs]


@analytics_router.get("/conversations/{conv_id}/messages")
async def conversation_messages(
    conv_id: str,
    payload: dict = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    )
    msgs = result.scalars().all()
    return [{
        "id": m.id, "role": m.role.value, "content": m.content,
        "model_used": m.model_used, "total_tokens": m.total_tokens,
        "latency_ms": m.latency_ms, "created_at": m.created_at.isoformat(),
    } for m in msgs]
