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


async def record_usage(db: AsyncSession, bot: Chatbot, tokens: int) -> None:
    """Suma tokens al contador del mes (atómico, reinicia al cambiar de mes) y dispara los avisos
    del 80% y 100% del límite una sola vez por mes y nivel."""
    month = current_month()
    row = (await db.execute(text("""
        UPDATE chatbots SET
            usage_alert_level  = CASE WHEN usage_month = :m THEN usage_alert_level ELSE 0 END,
            usage_month_tokens = CASE WHEN usage_month = :m THEN usage_month_tokens + :t ELSE :t END,
            usage_month        = :m
        WHERE id = :id
        RETURNING usage_month_tokens, usage_alert_level, monthly_token_limit
    """), {"m": month, "t": int(tokens or 0), "id": bot.id})).one()
    used, level, limit = row.usage_month_tokens, row.usage_alert_level, row.monthly_token_limit
    if not limit:
        return

    new_level = 100 if used >= limit else (80 if used >= 0.8 * limit else 0)
    if new_level > level:
        # Una sola instancia gana la carrera: el UPDATE condicional devuelve fila solo a quien sube el nivel.
        won = (await db.execute(text(
            "UPDATE chatbots SET usage_alert_level = :n WHERE id = :id AND usage_alert_level < :n RETURNING id"
        ), {"n": new_level, "id": bot.id})).first()
        if won:
            logger.warning("bot_token_limit_level", bot_id=bot.id, level=new_level, used=used, limit=limit)
            import asyncio
            asyncio.create_task(notify_bot_event(
                bot.id, f"limit-{new_level}",
                f"Bot '{bot.name}': {new_level}% del límite mensual de tokens",
                f"El chatbot '{bot.name}' ({bot.id}) consumió {used} de {limit} tokens este mes ({month})."
                + (" Dejará de responder hasta el mes próximo o hasta que se suba el límite." if new_level == 100 else ""),
            ))
