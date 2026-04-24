"""
app/services/ai_service.py — FIX #16: GoogleProvider history logic corregida
"""
import time
import json
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass
import structlog

from app.core.config import settings

logger = structlog.get_logger()


@dataclass
class ChatMessage:
    role: str
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


class BaseAIProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[ChatMessage], model: str,
                   temperature: float = 0.7, max_tokens: int = 1000) -> AIResponse:
        pass


class OpenAIProvider(BaseAIProvider):
    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def chat(self, messages, model="gpt-4o-mini", temperature=0.7, max_tokens=1000) -> AIResponse:
        start = time.monotonic()
        formatted = [{"role": m.role, "content": m.content} for m in messages]
        response = await self.client.chat.completions.create(
            model=model, messages=formatted,
            temperature=temperature, max_tokens=max_tokens,
        )
        return AIResponse(
            content=response.choices[0].message.content, model=model, provider="openai",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            latency_ms=int((time.monotonic() - start) * 1000),
        )


class AnthropicProvider(BaseAIProvider):
    def __init__(self):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def chat(self, messages, model="claude-3-haiku-20240307", temperature=0.7, max_tokens=1000) -> AIResponse:
        start = time.monotonic()
        system_content = ""
        chat_messages = []
        for m in messages:
            if m.role == "system":
                system_content = m.content
            else:
                chat_messages.append({"role": m.role, "content": m.content})
        kwargs = dict(model=model, max_tokens=max_tokens, temperature=temperature, messages=chat_messages)
        if system_content:
            kwargs["system"] = system_content
        response = await self.client.messages.create(**kwargs)
        return AIResponse(
            content=response.content[0].text, model=model, provider="anthropic",
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            latency_ms=int((time.monotonic() - start) * 1000),
        )


class GoogleProvider(BaseAIProvider):
    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.genai = genai

    async def chat(self, messages, model="gemini-2.5-flash-lite", temperature=0.7, max_tokens=1000) -> AIResponse:
        import asyncio
        start = time.monotonic()

        gen_model = self.genai.GenerativeModel(
            model_name=model,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )

        # FIX #16: construir historial correctamente
        system_parts = [m.content for m in messages if m.role == "system"]
        user_msgs = [m for m in messages if m.role != "system"]

        # Separar último mensaje de usuario del historial previo
        if not user_msgs:
            raise ValueError("No hay mensajes de usuario")

        last_user_msg = user_msgs[-1].content
        prior_messages = user_msgs[:-1]  # todos menos el último

        # Construir historial para Gemini (pares user/model)
        history = []
        for m in prior_messages:
            role = "user" if m.role == "user" else "model"
            history.append({"role": role, "parts": [m.content]})

        # Agregar system prompt al primer mensaje de usuario
        full_prompt = last_user_msg
        if system_parts:
            full_prompt = "\n".join(system_parts) + "\n\n" + last_user_msg

        chat_session = gen_model.start_chat(history=history)
        response = await asyncio.to_thread(chat_session.send_message, full_prompt)
        latency_ms = int((time.monotonic() - start) * 1000)

        return AIResponse(
            content=response.text, model=model, provider="google",
            prompt_tokens=getattr(response.usage_metadata, "prompt_token_count", 0),
            completion_tokens=getattr(response.usage_metadata, "candidates_token_count", 0),
            total_tokens=getattr(response.usage_metadata, "total_token_count", 0),
            latency_ms=latency_ms,
        )


class OllamaProvider(BaseAIProvider):
    def __init__(self):
        import httpx
        self.base_url = settings.OLLAMA_BASE_URL
        self.client = httpx.AsyncClient(timeout=120)

    async def chat(self, messages, model="llama3", temperature=0.7, max_tokens=1000) -> AIResponse:
        start = time.monotonic()
        formatted = [{"role": m.role, "content": m.content} for m in messages]
        response = await self.client.post(
            f"{self.base_url}/api/chat",
            json={"model": model, "messages": formatted, "stream": False,
                  "options": {"temperature": temperature, "num_predict": max_tokens}},
        )
        response.raise_for_status()
        data = response.json()
        return AIResponse(
            content=data["message"]["content"], model=model, provider="ollama",
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
        )


class AIService:
    _providers: dict[str, BaseAIProvider] = {}

    @classmethod
    def get_provider(cls, provider: str) -> BaseAIProvider:
        if provider not in cls._providers:
            match provider:
                case "openai":    cls._providers[provider] = OpenAIProvider()
                case "anthropic": cls._providers[provider] = AnthropicProvider()
                case "google":    cls._providers[provider] = GoogleProvider()
                case "ollama":    cls._providers[provider] = OllamaProvider()
                case _: raise ValueError(f"Proveedor desconocido: {provider}")
        return cls._providers[provider]

    @classmethod
    async def chat(cls, provider: str, model: str, messages: list[ChatMessage],
                   temperature: float = 0.7, max_tokens: int = 1000) -> AIResponse:
        from tenacity import retry, stop_after_attempt, wait_exponential

        @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
        async def _call():
            return await cls.get_provider(provider).chat(
                messages, model=model, temperature=temperature, max_tokens=max_tokens
            )
        try:
            return await _call()
        except Exception as e:
            logger.error("ai_service_error", provider=provider, model=model, error=str(e))
            raise
