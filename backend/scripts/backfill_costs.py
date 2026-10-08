"""scripts/backfill_costs.py — calcula el costo estimado de los mensajes anteriores a la columna de costo.

Qué hace: para cada respuesta del asistente con cost_usd NULL, calcula el costo de entrada y salida del
LLM con la tabla de precios (app/services/pricing.py) y lo guarda. Suma el mismo monto al total de costo
del bot.

Límites (son consultas que ya ocurrieron y no se registraron):
- Solo cubre el LLM: los embeddings de esas consultas no se guardaron, así que no se pueden recuperar.
- No cuenta caché de OpenAI (no se guardó); el costo queda levemente sobreestimado para esos modelos.
- Los modelos sin precio cargado quedan con cost_usd NULL.
- No toca los contadores del mes en curso (usage_month_cost_usd): reflejan solo lo registrado en vivo.

Uso (desde backend/, con el venv del servicio):
    .venv/bin/python scripts/backfill_costs.py          # simulación: muestra cuánto cambiaría
    .venv/bin/python scripts/backfill_costs.py --apply  # escribe los cambios (una sola transacción)
"""
import argparse
import asyncio
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sqlalchemy import select, update  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.models import Chatbot, Conversation, Message, MessageRole  # noqa: E402
from app.services.pricing import llm_cost_usd  # noqa: E402


async def run(apply: bool) -> None:
    # Muestra a qué base apunta (sin credenciales). Por defecto es la de backend/.env: la de producción.
    print(f"Base de datos: {settings.DATABASE_URL.split('@')[-1]}")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Message.id, Conversation.chatbot_id, Message.provider_used, Message.model_used,
                   Message.prompt_tokens, Message.completion_tokens)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Message.role == MessageRole.assistant, Message.cost_usd.is_(None))
        )).all()

        to_update: list[dict] = []
        per_bot: dict[str, float] = defaultdict(float)
        unpriced = 0
        for r in rows:
            cost = llm_cost_usd(r.provider_used or "", r.model_used or "",
                                r.prompt_tokens or 0, r.completion_tokens or 0)
            if cost is None:
                unpriced += 1
                continue
            to_update.append({"id": r.id, "cost_usd": cost})
            per_bot[r.chatbot_id] += cost

        total = sum(per_bot.values())
        print(f"Mensajes sin costo: {len(rows)}")
        print(f"  con precio (se calculan): {len(to_update)}  -> costo total USD {total:.4f}")
        print(f"  sin precio (quedan NULL): {unpriced}")
        print(f"  bots afectados: {len(per_bot)}")

        if not apply:
            print("Simulación: no se escribió nada. Para aplicar, correr con --apply.")
            return

        if to_update:
            await db.execute(update(Message), to_update)  # UPDATE por clave primaria, en lote
        for bot_id, cost in per_bot.items():
            await db.execute(update(Chatbot).where(Chatbot.id == bot_id)
                             .values(total_cost_usd=Chatbot.total_cost_usd + cost))
        await db.commit()
        print("Listo: cambios aplicados en una sola transacción.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="escribir los cambios (sin esto solo simula)")
    args = parser.parse_args()
    asyncio.run(run(args.apply))


if __name__ == "__main__":
    main()
