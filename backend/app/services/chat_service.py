"""
app/services/chat_service.py — Servicio de chat optimizado con JSON + RAG + historial
"""
import json
import time
from typing import Optional, AsyncGenerator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.models import Chatbot, Conversation, Message, MessageRole
from app.services.ai_service import AIService, ChatMessage
from app.services.rag_service import RAGService
from app.core.config import settings

logger = structlog.get_logger()

# Prompt base del sistema RAG
RAG_SYSTEM_TEMPLATE = """Eres {bot_name}, un asistente especializado. {personality}

INSTRUCCIONES:
- Responde ÚNICAMENTE basándote en el contexto proporcionado
- Si la información no está en el contexto, dilo claramente: "No tengo información sobre eso en mis documentos"
- Sé conciso, claro y útil
- Cita la fuente cuando sea relevante (página, documento)
- Idioma: responde siempre en el mismo idioma del usuario

CONTEXTO DE DOCUMENTOS:
{context}
"""

NO_CONTEXT_SYSTEM_TEMPLATE = """Eres {bot_name}. {personality}
Responde de forma útil y concisa. Si no sabes algo, dilo con honestidad."""


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.rag = RAGService(db)

    async def get_or_create_conversation(
        self,
        chatbot_id: str,
        session_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        user_identifier: Optional[str] = None,
    ) -> Conversation:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.chatbot_id == chatbot_id)
            .where(Conversation.session_id == session_id)
            .where(Conversation.is_active == True)
        )
        conv = result.scalar_one_or_none()

        if not conv:
            conv = Conversation(
                chatbot_id=chatbot_id,
                session_id=session_id,
                ip_address=ip_address,
                user_agent=user_agent,
                user_identifier=user_identifier,
            )
            self.db.add(conv)
            await self.db.flush()

        return conv

    async def get_history(self, conversation_id: str, max_messages: int = 10) -> list[ChatMessage]:
        """Obtiene historial reciente para el contexto del LLM."""
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .where(Message.role.in_([MessageRole.user, MessageRole.assistant]))
            .order_by(Message.created_at.desc())
            .limit(max_messages)
        )
        messages = list(reversed(result.scalars().all()))
        return [ChatMessage(role=m.role.value, content=m.content) for m in messages]

    async def chat(
        self,
        chatbot_id: str,
        session_id: str,
        user_message: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> dict:
        """
        Pipeline completo de chat:
        1. Obtener/crear conversación
        2. Buscar contexto RAG
        3. Construir prompt optimizado (JSON interno)
        4. Llamar al LLM
        5. Guardar mensaje + metadata
        6. Retornar respuesta JSON

        La comunicación INTERNA con el modelo usa JSON estructurado para:
        - Reducir tokens de sistema repetitivos
        - Respuestas más consistentes
        - Facilitar parsing de fuentes citadas
        """
        start = time.monotonic()

        # 1. Cargar chatbot config
        chatbot = await self.db.get(Chatbot, chatbot_id)
        if not chatbot or not chatbot.is_active:
            raise ValueError("Chatbot no disponible")

        # 2. Conversación
        conv = await self.get_or_create_conversation(chatbot_id, session_id, ip_address, user_agent)
        history = await self.get_history(conv.id)

        # 3. Búsqueda RAG
        rag_chunks = await self.rag.search(
            chatbot_id=chatbot_id,
            query=user_message,
            top_k=chatbot.top_k,
            threshold=chatbot.similarity_threshold,
        )

        # 4. Construir mensajes para el LLM
        personality = chatbot.system_prompt or "Sé amable, preciso y profesional."
        bot_name = chatbot.bot_name

        if rag_chunks:
            context = self.rag.build_context(rag_chunks, settings.MAX_CONTEXT_TOKENS)
            system_content = RAG_SYSTEM_TEMPLATE.format(
                bot_name=bot_name,
                personality=personality,
                context=context,
            )
        else:
            system_content = NO_CONTEXT_SYSTEM_TEMPLATE.format(
                bot_name=bot_name,
                personality=personality,
            )

        # Instrucción JSON interna para respuestas estructuradas (optimiza tokens)
        json_instruction = """
Responde en JSON con este esquema exacto:
{"answer": "tu respuesta aquí", "sources": ["doc.pdf p.2", ...], "confidence": 0.9}
Solo JSON, sin markdown ni explicaciones extra."""

        messages = [
            ChatMessage(role="system", content=system_content + json_instruction),
            *history,
            ChatMessage(role="user", content=user_message),
        ]

        # 5. Llamar al LLM
        ai_response = await AIService.chat(
            provider=chatbot.ai_provider.value,
            model=chatbot.ai_model,
            messages=messages,
            temperature=chatbot.temperature,
            max_tokens=chatbot.max_tokens,
        )

        # 6. Parsear respuesta JSON del LLM
        answer_text, sources, confidence = self._parse_json_response(ai_response.content)

        total_ms = int((time.monotonic() - start) * 1000)

        # 7. Guardar mensajes en BD
        user_msg = Message(
            conversation_id=conv.id,
            role=MessageRole.user,
            content=user_message,
        )
        assistant_msg = Message(
            conversation_id=conv.id,
            role=MessageRole.assistant,
            content=answer_text,
            model_used=chatbot.ai_model,
            provider_used=chatbot.ai_provider.value,
            prompt_tokens=ai_response.prompt_tokens,
            completion_tokens=ai_response.completion_tokens,
            total_tokens=ai_response.total_tokens,
            latency_ms=total_ms,
            retrieved_chunks=[
                {"content": c.content[:200], "score": c.score, "source": c.filename, "page": c.page_number}
                for c in rag_chunks
            ],
        )
        self.db.add_all([user_msg, assistant_msg])

        # 8. Actualizar estadísticas
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conv.id)
            .values(total_messages=Conversation.total_messages + 2, total_tokens=Conversation.total_tokens + ai_response.total_tokens)
        )
        await self.db.execute(
            update(Chatbot)
            .where(Chatbot.id == chatbot_id)
            .values(
                total_messages=Chatbot.total_messages + 2,
                total_tokens_used=Chatbot.total_tokens_used + ai_response.total_tokens,
            )
        )
        await self.db.commit()

        return {
            "answer": answer_text,
            "sources": sources,
            "confidence": confidence,
            "conversation_id": conv.id,
            "session_id": session_id,
            "tokens_used": ai_response.total_tokens,
            "latency_ms": total_ms,
            "model": f"{chatbot.ai_provider.value}/{chatbot.ai_model}",
            "context_used": len(rag_chunks) > 0,
        }

    def _parse_json_response(self, raw: str) -> tuple[str, list, float]:
        """Parsea respuesta JSON del LLM con fallback."""
        try:
            # Limpiar posibles backticks markdown
            clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            data = json.loads(clean)
            return (
                data.get("answer", raw),
                data.get("sources", []),
                float(data.get("confidence", 0.8)),
            )
        except (json.JSONDecodeError, KeyError):
            # Fallback: usar el texto raw
            return raw, [], 0.7
