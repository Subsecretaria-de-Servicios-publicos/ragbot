"""app/services/bot_keys.py — API key propia por chatbot y límite mensual de tokens.

Reglas:
- La key del proveedor de IA vive cifrada en chatbots.ai_api_key_encrypted; nunca se devuelve por la API.
- Un bot sin key propia NO responde (salvo Ollama, que no usa key).
- El consumo del mes se lleva en contadores del propio chatbot (sin sumar mensajes en cada request).
"""
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret
from app.models.models import Chatbot
from app.services.alert_service import notify_bot_event

logger = structlog.get_logger()

# Mensajes para el usuario final: genéricos a propósito (no revelan configuración interna).
MSG_UNAVAILABLE = "El asistente no está disponible en este momento. Intentá nuevamente más tarde."
MSG_LIMIT = "El asistente alcanzó su límite de uso mensual. Intentá nuevamente el mes próximo o contactá al administrador."


class BotUnavailable(Exception):
    """El bot no puede atender (sin key o sin cupo). Se responde 503 con un mensaje genérico;
    el detalle real ('reason') queda solo en logs/alertas."""

    def __init__(self, reason: str, public_message: str = MSG_UNAVAILABLE):
        super().__init__(reason)
        self.public_message = public_message


def current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def bot_api_key(bot: Chatbot) -> Optional[str]:
    """Key descifrada del bot, o None si no tiene. Usar solo para llamar al proveedor."""
    return decrypt_secret(bot.ai_api_key_encrypted) if bot.ai_api_key_encrypted else None


def require_bot_api_key(bot: Chatbot) -> Optional[str]:
    """Devuelve la key del bot; sin key propia el bot no responde (Ollama no usa key)."""
    if bot.ai_provider.value == "ollama":
        return None
    key = bot_api_key(bot)
    if not key:
        raise BotUnavailable(f"El bot {bot.id} no tiene API key propia configurada")
    return key


def month_usage(bot: Chatbot) -> int:
    """Tokens consumidos en el mes en curso (el contador guardado puede ser de un mes anterior)."""
    return int(bot.usage_month_tokens or 0) if bot.usage_month == current_month() else 0


def enforce_monthly_limit(bot: Chatbot) -> None:
    limit = bot.monthly_token_limit
    if limit and month_usage(bot) >= limit:
        raise BotUnavailable(
            f"El bot {bot.id} alcanzó su límite mensual ({month_usage(bot)}/{limit} tokens)", MSG_LIMIT
        )


async def record_usage(db: AsyncSession, bot_id: str, *, prompt: int = 0, completion: int = 0,
                       embedding: int = 0, cost_usd: float = 0.0) -> None:
    """Suma el consumo al bot: totales históricos (desglosados), contadores del mes y costo estimado.
    El límite mensual cuenta todos los tokens (entrada + salida + embeddings). Atómico; reinicia al
    cambiar de mes. Dispara los avisos del 80% y 100% una sola vez por mes y nivel."""
    month = current_month()
    tokens = int(prompt or 0) + int(completion or 0) + int(embedding or 0)
    cost = float(cost_usd or 0.0)
    row = (await db.execute(text("""
        UPDATE chatbots SET
            usage_alert_level      = CASE WHEN usage_month = :m THEN usage_alert_level ELSE 0 END,
            usage_month_tokens     = CASE WHEN usage_month = :m THEN usage_month_tokens + :t ELSE :t END,
            usage_month_cost_usd   = CASE WHEN usage_month = :m THEN usage_month_cost_usd + :c ELSE :c END,
            usage_month            = :m,
            total_tokens_used      = total_tokens_used + :t,
            total_prompt_tokens    = total_prompt_tokens + :p,
            total_completion_tokens = total_completion_tokens + :o,
            total_embedding_tokens = total_embedding_tokens + :e,
            total_cost_usd         = total_cost_usd + :c
        WHERE id = :id
        RETURNING name, usage_month_tokens, usage_alert_level, monthly_token_limit
    """), {"m": month, "t": tokens, "p": int(prompt or 0), "o": int(completion or 0),
           "e": int(embedding or 0), "c": cost, "id": bot_id})).one()
    used, level, limit = row.usage_month_tokens, row.usage_alert_level, row.monthly_token_limit
    if not limit:
        return

    new_level = 100 if used >= limit else (80 if used >= 0.8 * limit else 0)
    if new_level > level:
        # Una sola instancia gana la carrera: el UPDATE condicional devuelve fila solo a quien sube el nivel.
        won = (await db.execute(text(
            "UPDATE chatbots SET usage_alert_level = :n WHERE id = :id AND usage_alert_level < :n RETURNING id"
        ), {"n": new_level, "id": bot_id})).first()
        if won:
            logger.warning("bot_token_limit_level", bot_id=bot_id, level=new_level, used=used, limit=limit)
            import asyncio
            asyncio.create_task(notify_bot_event(
                bot_id, f"limit-{new_level}",
                f"Bot '{row.name}': {new_level}% del límite mensual de tokens",
                f"El chatbot '{row.name}' ({bot_id}) consumió {used} de {limit} tokens este mes ({month})."
                + (" Dejará de responder hasta el mes próximo o hasta que se suba el límite." if new_level == 100 else ""),
            ))
