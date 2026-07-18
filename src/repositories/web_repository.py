"""
Live web retrieval repository (Repository Pattern).

WebRepository is the interface the service layer depends on.
DuckDuckGoWebRepository is the current implementation — swapping to
Bing/Tavily/SerpAPI later means writing a new class against this same
Protocol, no orchestration changes required.

Every snippet is sanitized (src.repositories.sanitization) before being
wrapped into a WebSnippet, since this is the one context source that
comes from the open internet rather than our own data.
"""

import time
from typing import Protocol

from duckduckgo_search import DDGS
from duckduckgo_search.exceptions import DuckDuckGoSearchException

from src.core.exceptions import RetrievalError
from src.core.logging import get_logger
from src.repositories.sanitization import is_snippet_usable, sanitize_snippet
from src.schemas.retrieval import SourceType, WebSnippet

logger = get_logger("web_repository")


class WebRepository(Protocol):
    """Interface for retrieving live web search results relevant to a sport."""

    def search(self, sport: str, query_text: str, top_k: int) -> list[WebSnippet]:
        """Returns up to top_k sanitized web snippets for the given query."""
        ...


class DuckDuckGoWebRepository:
    """DuckDuckGo-backed implementation of WebRepository."""

    def __init__(self, max_retries: int = 2, backoff_seconds: float = 1.5) -> None:
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds

    def search(self, sport: str, query_text: str, top_k: int = 3) -> list[WebSnippet]:
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 2):  # +1 initial + retries
            try:
                raw_results = self._run_search(query_text, top_k)
                return self._to_snippets(raw_results)
            except (DuckDuckGoSearchException, TimeoutError, ConnectionError) as exc:
                last_error = exc
                logger.warning(
                    "web_search_attempt_failed",
                    sport=sport,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt <= self._max_retries:
                    time.sleep(self._backoff_seconds * attempt)

        # All attempts exhausted — surface a typed error, never the raw exception.
        raise RetrievalError(
            "web",
            f"search failed after {self._max_retries + 1} attempts: {last_error}",
        )

    def _run_search(self, query_text: str, top_k: int) -> list[dict]:
        with DDGS() as ddgs:
            return list(ddgs.text(query_text, max_results=top_k))

    def _to_snippets(self, raw_results: list[dict]) -> list[WebSnippet]:
        snippets: list[WebSnippet] = []
        for rank, r in enumerate(raw_results):
            raw_text = r.get("body", "")
            cleaned = sanitize_snippet(raw_text)

            if not is_snippet_usable(cleaned):
                logger.info("web_snippet_discarded", reason="unusable_after_sanitization")
                continue

            # DuckDuckGo already returns results in relevance order, so we
            # derive a decaying score from rank rather than claiming a real
            # similarity metric we don't have.
            rank_relevance = max(0.3, 0.9 - (rank * 0.15))

            snippets.append(
                WebSnippet(
                    title=sanitize_snippet(r.get("title", "Untitled")),
                    text=cleaned,
                    url=r.get("href"),
                    relevance_score=rank_relevance,
                    source_type=SourceType.WEB,
                )
            )

        logger.info("web_search_completed", result_count=len(snippets))
        return snippets
