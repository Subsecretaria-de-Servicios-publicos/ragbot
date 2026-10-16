"""
app/services/ai_service.py — Servicio multi-proveedor de IA con optimización de tokens
"""
import time
import json
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional
from dataclasses import dataclass
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx

from app.core.config import settings
from app.core.crypto import scrub_secrets

logger = structlog.get_logger()


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass
class AIResponse:
    content: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    cached_prompt_tokens: int = 0  # parte de prompt_tokens servida desde caché del proveedor (cobra menos)
    truncated: bool = False  # True si el proveedor cortó la respuesta por el límite de tokens (max_tokens)
    web_searches: int = 0  # búsquedas en internet que hizo el proveedor para esta respuesta (0 si no se pidió o no aplica)


# ─── Base Provider ────────────────────────────────────────────
class BaseAIProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        stream: bool = False,
        web_search: bool = False,
        web_search_max_uses: Optional[int] = None,
    ) -> AIResponse:
        pass


# ─── OpenAI Provider ─────────────────────────────────────────
class OpenAIProvider(BaseAIProvider):
    def __init__(self, api_key: Optional[str] = None):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    # Modelos de Chat Completions con búsqueda en internet integrada. A diferencia de Anthropic
    # y Google, OpenAI NO tiene un "tool" que se le agregue a cualquier modelo: la búsqueda es
    # una característica del modelo en sí. Si el bot usa gpt-4o/gpt-4o-mini con allow_web_search
    # activado, no hay nada que mandarle a la API — hay que elegir uno de estos modelos.
    SEARCH_MODELS = {"gpt-5-search-api", "gpt-4o-search-preview", "gpt-4o-mini-search-preview"}

    async def chat(self, messages, model="gpt-4o-mini", temperature=0.7, max_tokens=1000, stream=False,
                   web_search=False, web_search_max_uses=None) -> AIResponse:
        start = time.monotonic()
        formatted = [{"role": m.role, "content": m.content} for m in messages]

        if web_search and model not in self.SEARCH_MODELS:
            logger.warning("openai_web_search_unsupported_model", model=model,
                           hint="usar gpt-5-search-api (u otro modelo *-search-*) para que busque de verdad")

        response = await self.client.chat.completions.create(
            model=model,
            messages=formatted,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "text"},  # JSON optimizado
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        usage = response.usage
        details = getattr(usage, "prompt_tokens_details", None)
        cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
        return AIResponse(
            content=response.choices[0].message.content,
            model=model,
            provider="openai",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            latency_ms=latency_ms,
            cached_prompt_tokens=cached,
            truncated=response.choices[0].finish_reason == "length",
            # OpenAI no informa cuántas búsquedas hizo en Chat Completions: el costo de la
            # búsqueda ya viene mezclado en los tokens de la respuesta, no se cobra aparte.
            web_searches=0,
        )


# ─── Anthropic Provider ───────────────────────────────────────
class AnthropicProvider(BaseAIProvider):
    def __init__(self, api_key: Optional[str] = None):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key or settings.ANTHROPIC_API_KEY)

    # Tope por defecto si el bot tiene búsqueda activada pero no fijó uno propio: ver NOTE en
    # bot_keys/routers — sin esto, el modelo podría encadenar búsquedas sin límite en una sola
    # respuesta (cada una se cobra aparte, además de los tokens que agrega al contexto).
    DEFAULT_WEB_SEARCH_MAX_USES = 3

    async def chat(self, messages, model="claude-haiku-4-5-20251001", temperature=0.7, max_tokens=1000, stream=False,
                   web_search=False, web_search_max_uses=None) -> AIResponse:
        start = time.monotonic()

        # Separar system message
        system_content = ""
        chat_messages = []
        for m in messages:
            if m.role == "system":
                system_content = m.content
            else:
                chat_messages.append({"role": m.role, "content": m.content})

        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=chat_messages,
        )
        if system_content:
            kwargs["system"] = system_content
        if web_search:
            kwargs["tools"] = [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": web_search_max_uses or self.DEFAULT_WEB_SEARCH_MAX_USES,
            }]

        response = await self.client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)

        # Con búsqueda activada la respuesta trae varios bloques (texto, la búsqueda en sí, los
        # resultados, más texto) — el texto final es la concatenación de los bloques de tipo
        # "text", no solo el primero.
        text = "".join(b.text for b in response.content if b.type == "text")
        server_tool_use = getattr(response.usage, "server_tool_use", None)
        searches = getattr(server_tool_use, "web_search_requests", 0) if server_tool_use else 0

        return AIResponse(
            content=text,
            model=model,
            provider="anthropic",
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            latency_ms=latency_ms,
            truncated=response.stop_reason == "max_tokens",
            web_searches=searches or 0,
        )


# ─── Google Provider ──────────────────────────────────────────
GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GoogleRateLimited(Exception):
    """429 de la API de Google (cuota/rate limit): se reintenta con backoff."""


class GoogleProvider(BaseAIProvider):
    """Usa la API REST con la key en el header de CADA request. No se usa genai.configure():
    es estado global del proceso y, con una key por bot, una request podría salir con la key
    de otro bot (imputando el gasto donde no corresponde)."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GOOGLE_API_KEY

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=12, max=60),
        retry=retry_if_exception_type(GoogleRateLimited),
        reraise=True
    )
    async def chat(self, messages, model="gemini-2.5-flash-lite", temperature=0.7, max_tokens=1000, stream=False,
                   web_search=False, web_search_max_uses=None) -> AIResponse:
        # web_search_max_uses no se usa acá: Google no tiene un parámetro documentado para
        # limitar cuántas búsquedas hace el modelo por respuesta (a diferencia de Anthropic).
        # El único freno real para este proveedor es el límite mensual de tokens del bot.
        start = time.monotonic()

        # Convertir mensajes al formato Gemini
        system_parts = [m.content for m in messages if m.role == "system"]
        history = []
        last_user = ""
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "user":
                last_user = m.content
                if history:
                    history.append({"role": "user", "parts": [{"text": m.content}]})
            elif m.role == "assistant":
                history.append({"role": "model", "parts": [{"text": m.content}]})

        full_prompt = ("\n".join(system_parts) + "\n\n" + last_user).strip() if system_parts else last_user
        contents = (history[:-1] if history else []) + [{"role": "user", "parts": [{"text": full_prompt}]}]

        body = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if web_search:
            body["tools"] = [{"google_search": {}}]

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{GOOGLE_API_BASE}/models/{model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json=body,
            )
        if resp.status_code == 429:
            raise GoogleRateLimited("Google API 429 (cuota o rate limit)")
        if resp.status_code >= 400:
            # Solo el código: el cuerpo de error del proveedor no se propaga (podría reflejar datos sensibles)
            raise RuntimeError(f"Google API respondió {resp.status_code}")
        data = resp.json()
        latency_ms = int((time.monotonic() - start) * 1000)

        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
        text_out = "".join(p.get("text", "") for p in parts)
        if not text_out:
            reason = (candidates[0].get("finishReason") if candidates else None) or \
                     (data.get("promptFeedback") or {}).get("blockReason") or "sin contenido"
            raise ValueError(f"Google no devolvió una respuesta ({reason})")

        # Los modelos 2.5 "piensan" antes de responder: esos tokens se cobran como salida, pero
        # no vienen en candidatesTokenCount. Se suman para no subestimar el costo.
        usage = data.get("usageMetadata") or {}
        prompt = usage.get("promptTokenCount", 0)
        completion = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
        return AIResponse(
            content=text_out,
            model=model,
            provider="google",
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            latency_ms=latency_ms,
            cached_prompt_tokens=usage.get("cachedContentTokenCount", 0),
            truncated=(candidates[0].get("finishReason") == "MAX_TOKENS") if candidates else False,
            # groundingMetadata.webSearchQueries: una entrada por cada búsqueda que hizo el modelo.
            web_searches=len(((candidates[0].get("groundingMetadata") or {}).get("webSearchQueries") or [])) if candidates else 0,
        )


# ─── Ollama Provider (local) ──────────────────────────────────
class OllamaProvider(BaseAIProvider):
    def __init__(self, base_url: Optional[str] = None):
        import httpx
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.client = httpx.AsyncClient(timeout=120)

    async def chat(self, messages, model="llama3", temperature=0.7, max_tokens=1000, stream=False,
                   web_search=False, web_search_max_uses=None) -> AIResponse:
        # Ollama corre modelos locales: no hay búsqueda en internet posible acá.
        start = time.monotonic()
        formatted = [{"role": m.role, "content": m.content} for m in messages]

        response = await self.client.post(
            f"{self.base_url}/api/chat",
            json={"model": model, "messages": formatted, "stream": False,
                  "options": {"temperature": temperature, "num_predict": max_tokens}},
        )
        response.raise_for_status()
        data = response.json()
        latency_ms = int((time.monotonic() - start) * 1000)

        return AIResponse(
            content=data["message"]["content"],
            model=model,
            provider="ollama",
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            latency_ms=latency_ms,
            truncated=data.get("done_reason") == "length",
        )


# ─── Factory ──────────────────────────────────────────────────
class AIService:
    _providers: dict[str, BaseAIProvider] = {}

    @staticmethod
    def _build_provider(provider: str, api_key: Optional[str] = None, base_url: Optional[str] = None) -> BaseAIProvider:
        match provider:
            case "openai":
                return OpenAIProvider(api_key=api_key)
            case "anthropic":
                return AnthropicProvider(api_key=api_key)
            case "google":
                return GoogleProvider(api_key=api_key)
            case "ollama":
                return OllamaProvider(base_url=base_url)
            case _:
                raise ValueError(f"Proveedor IA desconocido: {provider}")

    @classmethod
    def get_provider(cls, provider: str) -> BaseAIProvider:
        if provider not in cls._providers:
            cls._providers[provider] = cls._build_provider(provider)
        return cls._providers[provider]

    @classmethod
    async def chat(
        cls,
        provider: str,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        web_search: bool = False,
        web_search_max_uses: Optional[int] = None,
    ) -> AIResponse:
        # Reintentos genéricos para errores temporales (red, timeouts, etc.)
        # El proveedor Google tiene sus propios reintentos específicos para cuotas.
        @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
        async def _call():
            # Si hay override (key/base_url configurados en BD por el superadmin), construir
            # una instancia nueva en vez de usar el singleton cacheado (que sigue sirviendo
            # a bots que no configuraron nada y usan las credenciales de .env).
            p = cls._build_provider(provider, api_key, base_url) if (api_key or base_url) else cls.get_provider(provider)
            return await p.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens,
                                web_search=web_search, web_search_max_uses=web_search_max_uses)

        try:
            return await _call()
        except Exception as e:
            logger.error("ai_service_error", provider=provider, model=model, error=scrub_secrets(str(e)))
            raise
