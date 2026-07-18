"""
Domain exceptions.

Each layer raises a specific exception type so callers can catch precisely
(e.g. the service layer can catch RetrievalError separately from
GenerationError and apply different fallback behavior) instead of a blanket
`except Exception`, which hides bugs and makes error handling untestable.
"""


class QuizAgentError(Exception):
    """Base class for all domain errors raised by this application."""


class ConfigurationError(QuizAgentError):
    """Raised when required configuration is missing or invalid."""


class RetrievalError(QuizAgentError):
    """Raised when a retriever (local or web) fails to fetch context."""

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        super().__init__(f"[{source}] retrieval failed: {message}")


class NoContextAvailableError(RetrievalError):
    """Raised when both local and web retrieval return nothing usable."""


class GenerationError(QuizAgentError):
    """Raised when the LLM call itself fails (network, auth, rate limit)."""


class SchemaValidationError(QuizAgentError):
    """
    Raised when LLM output cannot be validated against the expected
    Pydantic schema, even after retries and the fallback parser.
    """

    def __init__(self, raw_output: str, message: str) -> None:
        self.raw_output = raw_output
        super().__init__(f"Schema validation failed: {message}")


class DataLoadError(QuizAgentError):
    """Raised when local fact data (sports_facts.json) fails to load or validate."""


class RateLimitExceededError(QuizAgentError):
    """
    Raised when a caller exceeds the configured request rate.

    Kept as a distinct type (not GenerationError) so the UI layer can show
    a specific "slow down" message rather than a generic failure.
    """

    def __init__(self, identity: str, retry_after_seconds: float) -> None:
        self.identity = identity
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Rate limit exceeded for {identity!r}; retry after {retry_after_seconds:.1f}s"
        )
