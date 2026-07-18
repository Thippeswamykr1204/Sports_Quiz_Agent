"""
Centralized application configuration.

Fail Fast Configuration principle: this module raises at import time if
required settings are missing or malformed, instead of letting a request
fail deep inside the pipeline with an unhelpful error.

Usage:
    from src.config.settings import get_settings
    settings = get_settings()
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM provider ---
# --- LLM provider ---
    google_api_key: str = Field(
        ...,
        description="Google Gemini API key."
    )

    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model."
    )

    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    # --- Prompt versioning ---
    active_prompt_version: str = Field(default="v2")

    # --- Retrieval ---
    chroma_persist_dir: Path = Field(default=Path("./chroma_db"))
    sports_facts_path: Path = Field(default=Path("./data/sports_facts.json"))
    local_retrieval_top_k: int = Field(default=3, ge=1, le=20)
    web_retrieval_top_k: int = Field(default=3, ge=1, le=10)

    # --- Context compression ---
    max_context_tokens: int = Field(default=1500, ge=200, le=8000)

    # --- Caching ---
    cache_dir: Path = Field(default=Path("./.cache"))
    cache_ttl_seconds: int = Field(default=6 * 60 * 60)  # 6 hours

    # --- Observability ---
    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    @field_validator("google_api_key")
    @classmethod
    def _key_not_placeholder(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError(
                "GOOGLE_API_KEY is missing. Set a real key in your .env file."
            )
        return v

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return upper


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached Settings singleton.

    Cached deliberately: Settings() re-parses env/`.env` on every call,
    which is wasteful and would let config drift mid-process. lru_cache
    gives us a single source of truth for the process lifetime.
    """
    return Settings()