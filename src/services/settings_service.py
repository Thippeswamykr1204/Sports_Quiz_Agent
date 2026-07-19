"""
Settings service - typed read/write layer over SettingsRepository.

Every setting falls back to the environment-configured default
(src/config/settings.py) until the user explicitly overrides it via the
Settings page, at which point the override is persisted and wins on
every subsequent read - including after a restart. Applying a value
that affects the generation pipeline (model, temperature, prompt
version, cache TTL) requires rebuilding QuizService - this service only
owns storage; app.py decides when to rebuild (via st.cache_resource.clear()).
"""

from dataclasses import dataclass

from src.config.settings import Settings, get_settings
from src.core.logging import get_logger
from src.generation.prompts import PROMPTS
from src.repositories.settings_repository import SettingsRepository

logger = get_logger("settings_service")

# Real, known Gemini model identifiers - not an exhaustive live catalog
# (that would need a network call to Google's model-listing API), but a
# curated list of models this app is known to work with. The
# environment-configured default is always included even if a future
# model name isn't in this list yet.
AVAILABLE_MODELS = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]

_KEY_THEME = "theme"
_KEY_MODEL = "gemini_model"
_KEY_TEMPERATURE = "llm_temperature"
_KEY_MAX_QUESTIONS = "max_questions"
_KEY_CONFIDENCE_THRESHOLD = "confidence_threshold"
_KEY_PROMPT_VERSION = "active_prompt_version"
_KEY_CACHE_TTL_HOURS = "cache_ttl_hours"


@dataclass(frozen=True)
class ResolvedSettings:
    """One consistent snapshot - what app.py reads to (re)build QuizService."""

    theme: str
    model: str
    temperature: float
    max_questions: int
    confidence_threshold: float
    prompt_version: str
    cache_ttl_hours: float


class SettingsService:
    def __init__(self, repository: SettingsRepository, env_settings: Settings | None = None) -> None:
        self._repository = repository
        self._env_settings = env_settings or get_settings()

    # --- typed-read helpers -------------------------------------------------

    def _get_float(self, key: str, default: float) -> float:
        stored = self._repository.get(key)
        if stored is None:
            return default
        try:
            return float(stored)
        except ValueError:
            logger.warning("corrupted_setting_value_ignored", key=key, value=stored)
            return default

    def _get_int(self, key: str, default: int) -> int:
        stored = self._repository.get(key)
        if stored is None:
            return default
        try:
            return int(stored)
        except ValueError:
            logger.warning("corrupted_setting_value_ignored", key=key, value=stored)
            return default

    # --- individual typed getters/setters ---------------------------------

    def get_theme(self) -> str:
        return self._repository.get(_KEY_THEME) or "Dark"

    def set_theme(self, value: str) -> None:
        self._repository.set(_KEY_THEME, value)

    def get_model(self) -> str:
        return self._repository.get(_KEY_MODEL) or self._env_settings.gemini_model

    def set_model(self, value: str) -> None:
        self._repository.set(_KEY_MODEL, value)

    def get_temperature(self) -> float:
        return self._get_float(_KEY_TEMPERATURE, self._env_settings.llm_temperature)

    def set_temperature(self, value: float) -> None:
        self._repository.set(_KEY_TEMPERATURE, str(value))

    def get_max_questions(self) -> int:
        return self._get_int(_KEY_MAX_QUESTIONS, 6)

    def set_max_questions(self, value: int) -> None:
        self._repository.set(_KEY_MAX_QUESTIONS, str(value))

    def get_confidence_threshold(self) -> float:
        return self._get_float(_KEY_CONFIDENCE_THRESHOLD, 0.5)

    def set_confidence_threshold(self, value: float) -> None:
        self._repository.set(_KEY_CONFIDENCE_THRESHOLD, str(value))

    def get_prompt_version(self) -> str:
        return self._repository.get(_KEY_PROMPT_VERSION) or self._env_settings.active_prompt_version

    def set_prompt_version(self, value: str) -> None:
        if value not in PROMPTS:
            raise ValueError(f"Unknown prompt version: {value}. Available: {list(PROMPTS.keys())}")
        self._repository.set(_KEY_PROMPT_VERSION, value)

    def get_cache_ttl_hours(self) -> float:
        return self._get_float(_KEY_CACHE_TTL_HOURS, self._env_settings.cache_ttl_seconds / 3600)

    def set_cache_ttl_hours(self, value: float) -> None:
        self._repository.set(_KEY_CACHE_TTL_HOURS, str(value))

    # --- convenience -------------------------------------------------------

    def resolve(self) -> ResolvedSettings:
        return ResolvedSettings(
            theme=self.get_theme(),
            model=self.get_model(),
            temperature=self.get_temperature(),
            max_questions=self.get_max_questions(),
            confidence_threshold=self.get_confidence_threshold(),
            prompt_version=self.get_prompt_version(),
            cache_ttl_hours=self.get_cache_ttl_hours(),
        )

    def has_any_overrides(self) -> bool:
        return len(self._repository.get_all()) > 0

    def available_prompt_versions(self) -> list[str]:
        return sorted(PROMPTS.keys())