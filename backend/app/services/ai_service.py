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
from google.api_core.exceptions import ResourceExhausted

from app.core.config import settings

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
    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

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
    def __init__(self):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

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
class GoogleProvider(BaseAIProvider):
    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.genai = genai

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=12, max=60),
        retry=retry_if_exception_type(ResourceExhausted),
        reraise=True
    )
    async def chat(self, messages, model="gemini-2.5-flash-lite", temperature=0.7, max_tokens=1000, stream=False) -> AIResponse:
        import asyncio
        start = time.monotonic()

        gen_model = self.genai.GenerativeModel(
            model_name=model,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )

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
                    history.append({"role": "user", "parts": [m.content]})
            elif m.role == "assistant":
                history.append({"role": "model", "parts": [m.content]})

        chat_session = gen_model.start_chat(history=history[:-1] if history else [])
        full_prompt = ("\n".join(system_parts) + "\n\n" + last_user).strip() if system_parts else last_user
        response = await asyncio.to_thread(chat_session.send_message, full_prompt)
        latency_ms = int((time.monotonic() - start) * 1000)

        return AIResponse(
            content=response.text,
            model=model,
            provider="google",
            prompt_tokens=getattr(response.usage_metadata, "prompt_token_count", 0),
            completion_tokens=getattr(response.usage_metadata, "candidates_token_count", 0),
            total_tokens=getattr(response.usage_metadata, "total_token_count", 0),
            latency_ms=latency_ms,
        )


# ─── Ollama Provider (local) ──────────────────────────────────
class OllamaProvider(BaseAIProvider):
    def __init__(self):
        import httpx
        self.base_url = settings.OLLAMA_BASE_URL
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

    @classmethod
    def get_provider(cls, provider: str) -> BaseAIProvider:
        if provider not in cls._providers:
            match provider:
                case "openai":
                    cls._providers[provider] = OpenAIProvider()
                case "anthropic":
                    cls._providers[provider] = AnthropicProvider()
                case "google":
                    cls._providers[provider] = GoogleProvider()
                case "ollama":
                    cls._providers[provider] = OllamaProvider()
                case _:
                    raise ValueError(f"Proveedor IA desconocido: {provider}")
        return cls._providers[provider]

    @classmethod
    async def chat(
        cls,
        provider: str,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> AIResponse:
        # Reintentos genéricos para errores temporales (red, timeouts, etc.)
        # El proveedor Google tiene sus propios reintentos específicos para cuotas.
        @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
        async def _call():
            p = cls.get_provider(provider)
            return await p.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)

        try:
            return await _call()
        except Exception as e:
            logger.error("ai_service_error", provider=provider, model=model, error=str(e))
            raise
