"""app/services/pricing.py — precios de referencia para estimar el costo en USD del consumo.

Son precios de LISTA en USD por 1M de tokens, al momento de escribir esto. Los proveedores los
cambian: revisarlos contra la página de precios de cada uno antes de tomar decisiones de presupuesto.

Reglas:
- Si el modelo no está en la tabla, el costo queda en None (no se inventa un precio) y se loguea.
- El costo se calcula al momento de la llamada y se guarda en el mensaje: un cambio de precio
  futuro no altera el histórico.
- Ollama y sentence-transformers corren localmente: costo 0 (sin cobro de API).
"""
from typing import Optional

import structlog

logger = structlog.get_logger()

# (proveedor, modelo) -> (entrada, salida, entrada cacheada) en USD / 1M tokens.
# La entrada cacheada es None cuando el proveedor no descuenta caché para ese modelo.
LLM_PRICES: dict[tuple[str, str], tuple[float, float, Optional[float]]] = {
    ("openai", "gpt-4o"): (2.50, 10.00, 1.25),
    ("openai", "gpt-4o-mini"): (0.15, 0.60, 0.075),
    ("openai", "gpt-4-turbo"): (10.00, 30.00, None),
    ("openai", "gpt-3.5-turbo"): (0.50, 1.50, None),
    ("anthropic", "claude-3-5-sonnet-20241022"): (3.00, 15.00, None),
    ("anthropic", "claude-3-haiku-20240307"): (0.25, 1.25, None),
    ("anthropic", "claude-3-opus-20240229"): (15.00, 75.00, None),
    ("google", "gemini-1.5-pro"): (1.25, 5.00, None),
    ("google", "gemini-1.5-flash"): (0.075, 0.30, None),
    ("google", "gemini-2.5-flash-lite"): (0.10, 0.40, None),
    ("google", "gemini-2.5-flash"): (0.30, 2.50, None),
}

# (proveedor, modelo normalizado) -> USD / 1M tokens de entrada.
EMBEDDING_PRICES: dict[tuple[str, str], float] = {
    ("openai", "text-embedding-3-small"): 0.02,
    ("google", "gemini-embedding-001"): 0.15,
}

LOCAL_PROVIDERS = {"ollama", "sentence_transformers"}


def estimate_tokens(texts: list[str]) -> int:
    """Aproximación cuando el proveedor no informa tokens: ~4 caracteres por token."""
    return sum((len(t) + 3) // 4 for t in texts)


def _normalize_model(model: str) -> str:
    return (model or "").removeprefix("models/")


def llm_cost_usd(provider: str, model: str, prompt_tokens: int, completion_tokens: int,
                 cached_prompt_tokens: int = 0) -> Optional[float]:
    """Costo estimado de una llamada de chat. None si el modelo no tiene precio cargado."""
    if provider in LOCAL_PROVIDERS:
        return 0.0
    price = LLM_PRICES.get((provider, _normalize_model(model)))
    if price is None:
        logger.warning("pricing_unknown_model", provider=provider, model=model)
        return None
    price_in, price_out, price_cached = price
    cached = max(0, min(cached_prompt_tokens, prompt_tokens))
    if price_cached is None:
        cached_cost = 0.0
        uncached = prompt_tokens
    else:
        cached_cost = cached * price_cached
        uncached = prompt_tokens - cached
    return (uncached * price_in + cached_cost + completion_tokens * price_out) / 1_000_000


def embedding_cost_usd(provider: str, model: str, tokens: int) -> Optional[float]:
    """Costo estimado de embeddings. None si el modelo no tiene precio cargado."""
    if provider in LOCAL_PROVIDERS:
        return 0.0
    price = EMBEDDING_PRICES.get((provider, _normalize_model(model)))
    if price is None:
        logger.warning("pricing_unknown_embedding_model", provider=provider, model=model)
        return None
    return tokens * price / 1_000_000
