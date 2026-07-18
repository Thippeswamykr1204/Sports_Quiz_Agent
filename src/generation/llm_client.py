"""
Thin LLM client wrapper.

Isolates the OpenAI SDK behind one function so generation logic (prompt
building, schema validation) never touches the SDK directly — makes
multi-provider support (a Future Enhancement) a matter of adding a new
client class, not rewriting quiz_generator.py.

Always requests JSON-mode output (response_format={"type":"json_object"})
so quiz_generator.py never has to regex-parse free text.
"""

import time
from typing import Protocol

from openai import APIConnectionError, APIError, APIStatusError, OpenAI, RateLimitError

from src.core.exceptions import GenerationError
from src.core.logging import get_logger

logger = get_logger("llm_client")

_RETRYABLE_EXCEPTIONS = (APIConnectionError, RateLimitError, APIStatusError)


class LLMClient(Protocol):
    """Interface for calling an LLM and getting back raw JSON text."""

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        """Returns the raw text of the model's JSON-mode response."""
        ...


class OpenAILLMClient:
    """OpenAI-backed implementation of LLMClient."""

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        max_retries: int = 2,
        backoff_seconds: float = 2.0,
    ) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 2):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=self._temperature,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                if not content:
                    raise GenerationError("LLM returned an empty response body.")
                return content

            except _RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                logger.warning("llm_call_attempt_failed", attempt=attempt, error=str(exc))
                if attempt <= self._max_retries:
                    time.sleep(self._backoff_seconds * attempt)

            except APIError as exc:
                # Non-retryable API errors (bad request, auth, etc.) — fail immediately.
                raise GenerationError(f"LLM call failed (non-retryable): {exc}") from exc

        raise GenerationError(
            f"LLM call failed after {self._max_retries + 1} attempts: {last_error}"
        )
