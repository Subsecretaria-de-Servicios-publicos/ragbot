"""
app/core/config.py — Configuración centralizada con Pydantic Settings
"""
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_NAME: str = "RAGBot System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    DATABASE_URL: str
    DATABASE_URL_SYNC: str

    REDIS_URL: str = "redis://localhost:6379/0"

    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    DEFAULT_EMBEDDING_PROVIDER: str = "google"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    # FIX #1: embedding-001 DEPRECADO → text-embedding-004 (768 dims)
    GOOGLE_EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    EMBEDDING_DIMENSION: int = 768

    # Google embedding rate limiting (free tier = 100 req/min)
    # BATCH_SIZE: requests por lote antes de pausar
    # DELAY: segundos de pausa entre lotes (3.5s * 20 lotes = ~70 req/min, seguro)
    GOOGLE_EMBED_BATCH_SIZE: int = 20
    GOOGLE_EMBED_DELAY: float = 3.5

    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    TOP_K_RESULTS: int = 5
    MAX_CONTEXT_TOKENS: int = 4000

    ALLOWED_ORIGINS: str = "http://localhost:3000"
    ALLOWED_METHODS: str = "GET,POST,PUT,DELETE,OPTIONS"
    ALLOWED_HEADERS: str = "*"

    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 50

    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/ragbot.log"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
