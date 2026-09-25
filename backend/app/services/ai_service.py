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
    ) -> AIResponse:
        pass


# ─── OpenAI Provider ─────────────────────────────────────────
class OpenAIProvider(BaseAIProvider):
    def __init__(self, api_key: Optional[str] = None):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    async def chat(self, messages, model="gpt-4o-mini", temperature=0.7, max_tokens=1000, stream=False) -> AIResponse:
        start = time.monotonic()
        formatted = [{"role": m.role, "content": m.content} for m in messages]

        response = await self.client.chat.completions.create(
            model=model,
            messages=formatted,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "text"},  # JSON optimizado
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        return AIResponse(
            content=response.choices[0].message.content,
            model=model,
            provider="openai",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            latency_ms=latency_ms,
        )


# ─── Anthropic Provider ───────────────────────────────────────
class AnthropicProvider(BaseAIProvider):
    def __init__(self, api_key: Optional[str] = None):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key or settings.ANTHROPIC_API_KEY)

    async def chat(self, messages, model="claude-3-haiku-20240307", temperature=0.7, max_tokens=1000, stream=False) -> AIResponse:
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

        response = await self.client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)

        return AIResponse(
            content=response.content[0].text,
            model=model,
            provider="anthropic",
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            latency_ms=latency_ms,
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
    async def chat(self, messages, model="gemini-2.5-flash-lite", temperature=0.7, max_tokens=1000, stream=False) -> AIResponse:
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

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{GOOGLE_API_BASE}/models/{model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json={
                    "contents": contents,
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
                },
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

        usage = data.get("usageMetadata") or {}
        return AIResponse(
            content=text_out,
            model=model,
            provider="google",
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
            total_tokens=usage.get("totalTokenCount", 0),
            latency_ms=latency_ms,
        )


# ─── Ollama Provider (local) ──────────────────────────────────
class OllamaProvider(BaseAIProvider):
    def __init__(self, base_url: Optional[str] = None):
        import httpx
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.client = httpx.AsyncClient(timeout=120)

    async def chat(self, messages, model="llama3", temperature=0.7, max_tokens=1000, stream=False) -> AIResponse:
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
    ) -> AIResponse:
        # Reintentos genéricos para errores temporales (red, timeouts, etc.)
        # El proveedor Google tiene sus propios reintentos específicos para cuotas.
        @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
        async def _call():
            # Si hay override (key/base_url configurados en BD por el superadmin), construir
            # una instancia nueva en vez de usar el singleton cacheado (que sigue sirviendo
            # a bots que no configuraron nada y usan las credenciales de .env).
            p = cls._build_provider(provider, api_key, base_url) if (api_key or base_url) else cls.get_provider(provider)
            return await p.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)

        try:
            return await _call()
        except Exception as e:
            logger.error("ai_service_error", provider=provider, model=model, error=scrub_secrets(str(e)))
            raise
