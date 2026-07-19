import time

from google import genai

from src.core.exceptions import GenerationError
from src.core.logging import get_logger

logger = get_logger("gemini_client")

_RETRYABLE_EXCEPTION_NAMES = {"ServerError", "APIError", "DeadlineExceededError"}


class GeminiLLMClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        temperature: float = 0.7,
        max_retries: int = 2,
        backoff_seconds: float = 2.0,
    ):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        # Real metadata from the most recent call - never fabricated.
        # None means "not available", not 0.
        self._last_retry_count = 0
        self._last_token_usage: dict[str, int] | None = None

    def get_last_call_metadata(self) -> dict:
        """
        Additive introspection hook for AI Transparency Mode - not part of
        the LLMClient Protocol, so callers must getattr()/hasattr() guard
        rather than assume every LLMClient implementation has this.
        """
        return {
            "retry_count": self._last_retry_count,
            "token_usage": self._last_token_usage,
        }

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        self._last_retry_count = 0
        self._last_token_usage = None
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 2):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=f"{system_prompt}\n\n{user_prompt}",
                    config={
                        "temperature": self._temperature,
                        "response_mime_type": "application/json",
                    },
                )
                if not response.text:
                    raise GenerationError("Gemini returned an empty response.")

                usage = getattr(response, "usage_metadata", None)
                if usage is not None:
                    self._last_token_usage = {
                        "prompt_tokens": getattr(usage, "prompt_token_count", None),
                        "response_tokens": getattr(usage, "candidates_token_count", None),
                        "total_tokens": getattr(usage, "total_token_count", None),
                    }

                return response.text

            except GenerationError:
                raise
            except Exception as exc:
                last_error = exc
                retryable = type(exc).__name__ in _RETRYABLE_EXCEPTION_NAMES
                logger.warning("gemini_call_attempt_failed", attempt=attempt, error=str(exc), retryable=retryable)
                if not retryable or attempt > self._max_retries:
                    raise GenerationError(f"Gemini call failed: {exc}") from exc
                self._last_retry_count = attempt
                time.sleep(self._backoff_seconds * attempt)

        raise GenerationError(f"Gemini call failed after {self._max_retries + 1} attempts: {last_error}")