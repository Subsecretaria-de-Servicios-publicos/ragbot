"""
app/models/ — Todos los modelos SQLAlchemy con pgvector
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String, Text, Boolean, Integer, Float, DateTime,
    ForeignKey, JSON, Enum as SAEnum, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
import enum

from app.db.session import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


# ─── Enums ───────────────────────────────────────────────────
class UserRole(str, enum.Enum):
    superadmin = "superadmin"
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class AIProvider(str, enum.Enum):
    openai = "openai"
    anthropic = "anthropic"
    google = "google"
    ollama = "ollama"


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    error = "error"


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


# ─── User ────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.viewer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chatbots: Mapped[List["Chatbot"]] = relationship("Chatbot", back_populates="owner")


# ─── Chatbot ─────────────────────────────────────────────────
class Chatbot(Base):
    __tablename__ = "chatbots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)

    # AI Config
    ai_provider: Mapped[AIProvider] = mapped_column(SAEnum(AIProvider), default=AIProvider.openai)
    ai_model: Mapped[str] = mapped_column(String(100), default="gpt-4o-mini")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1000)

    # Personality
    system_prompt: Mapped[Optional[str]] = mapped_column(Text)
    welcome_message: Mapped[str] = mapped_column(Text, default="¡Hola! ¿En qué puedo ayudarte?")
    bot_name: Mapped[str] = mapped_column(String(100), default="Asistente")
    bot_avatar_url: Mapped[Optional[str]] = mapped_column(String(500))

    # Widget Config (JSON)
    widget_config: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    # Ejemplo: {"primary_color": "#3B82F6", "position": "bottom-right", "show_branding": true}

    # RAG Config
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    similarity_threshold: Mapped[float] = mapped_column(Float, default=0.7)

    # Stats
    total_conversations: Mapped[int] = mapped_column(Integer, default=0)
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped["User"] = relationship("User", back_populates="chatbots")
    documents: Mapped[List["Document"]] = relationship("Document", back_populates="chatbot", cascade="all, delete-orphan")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="chatbot")


# ─── Document ────────────────────────────────────────────────
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    chatbot_id: Mapped[str] = mapped_column(String(36), ForeignKey("chatbots.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    status: Mapped[DocumentStatus] = mapped_column(SAEnum(DocumentStatus), default=DocumentStatus.pending)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chatbot: Mapped["Chatbot"] = relationship("Chatbot", back_populates="documents")
    chunks: Mapped[List["DocumentChunk"]] = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


# ─── DocumentChunk (con vector pgvector) ─────────────────────
class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"))
    chatbot_id: Mapped[str] = mapped_column(String(36), ForeignKey("chatbots.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    page_number: Mapped[Optional[int]] = mapped_column(Integer)
    chunk_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Vector embedding — dimensión configurable
    embedding = mapped_column(Vector(1536))  # Cambiar si se usa otro modelo

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_chatbot_id", "chatbot_id"),
        # Índice HNSW para búsqueda de similitud rápida
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


# ─── Conversation ─────────────────────────────────────────────
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    chatbot_id: Mapped[str] = mapped_column(String(36), ForeignKey("chatbots.id"))
    session_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_identifier: Mapped[Optional[str]] = mapped_column(String(255))  # email o fingerprint
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_activity: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    chatbot: Mapped["Chatbot"] = relationship("Chatbot", back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


# ─── Message ─────────────────────────────────────────────────
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[MessageRole] = mapped_column(SAEnum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Metadata del LLM
    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    provider_used: Mapped[Optional[str]] = mapped_column(String(50))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)

    # Chunks usados para generar la respuesta
    retrieved_chunks: Mapped[Optional[list]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


# ─── APIKey ───────────────────────────────────────────────────
class APIKey(Base):
    """Claves API para acceso externo al chatbot (sitios embebidos)."""
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    chatbot_id: Mapped[str] = mapped_column(String(36), ForeignKey("chatbots.id", ondelete="CASCADE"))
    key_hash: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="Default")
    allowed_origins: Mapped[Optional[list]] = mapped_column(JSONB)  # Lista de dominios permitidos
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    requests_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
