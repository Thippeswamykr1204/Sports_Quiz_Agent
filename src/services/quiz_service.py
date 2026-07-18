"""
Quiz service — orchestration layer (Service Layer pattern).

Owns the full use case: validate -> build queries -> retrieve (local +
web) -> merge/dedupe -> compress -> generate -> cache. This is the only
class the UI layer (M6) talks to; it never imports chromadb, duckduckgo,
or openai directly — those live behind the repositories/generation
abstractions this service composes.

Retrieval is partial-tolerant: if one source fails, the service logs a
warning and proceeds with whatever context it has. Only a total absence
of context (both sources empty/failed) is treated as fatal.
"""

import time

from src.core.cache import QuizCache
from src.core.exceptions import NoContextAvailableError, RateLimitExceededError, RetrievalError
from src.core.logging import get_logger
from src.core.rate_limiter import RateLimiter
from src.core.request_context import request_scope
from src.generation.context_compressor import compress_context
from src.generation.llm_client import LLMClient
from src.generation.quiz_generator import generate_quiz
from src.repositories.fact_repository import FactRepository
from src.repositories.web_repository import WebRepository
from src.schemas.quiz import GenerationRequest, Quiz, SourceAttribution
from src.schemas.retrieval import MergedContext, RetrievedFact, SourceType, WebSnippet
from src.services.merge import merge_and_deduplicate
from src.services.query_builder import build_local_query, build_web_query

logger = get_logger("quiz_service")

_MAX_SOURCES_SHOWN = 5


def _attribute_sources(quiz: Quiz, merged: MergedContext) -> Quiz:
    """
    Attaches grounding source attribution to every question.

    NOTE: this attaches the same top-N merged-context items to every
    question in the quiz, since the LLM's JSON output does not currently
    return per-question citation indices — all questions are grounded in
    the same compressed context, so this is an honest (if coarse)
    representation of "what informed this quiz", not a false claim of
    per-question precision. Per-question citation tracing (asking the
    LLM to return a source index per question) is a Future Enhancement.
    """
    top_items = sorted(merged.items, key=lambda i: i.relevance_score, reverse=True)[
        :_MAX_SOURCES_SHOWN
    ]

    attributions = []
    for item in top_items:
        if isinstance(item, RetrievedFact):
            attributions.append(
                SourceAttribution(
                    source_type=SourceType.LOCAL_KB,
                    label="Local Knowledge Base",
                    url=None,
                    excerpt=item.text,
                )
            )
        elif isinstance(item, WebSnippet):
            attributions.append(
                SourceAttribution(
                    source_type=SourceType.WEB,
                    label=item.title,
                    url=item.url,
                    excerpt=item.text,
                )
            )

    for question in quiz.questions:
        question.sources = attributions

    return quiz


def _audit(request_id: str, request: GenerationRequest, outcome: str) -> None:
    """
    Emits a single structured audit-log line per request outcome.

    Kept deliberately minimal (no PII, no free text from the user or the
    LLM) — sport/difficulty are closed enums, outcome is a fixed set of
    known strings, so this line is always safe to ship to a log
    aggregator without a redaction pass.
    """
    logger.info(
        "audit_event",
        request_id=request_id,
        sport=request.sport.value,
        difficulty=request.difficulty.value,
        outcome=outcome,
    )


class QuizService:
    """Coordinates retrieval, generation, and caching for a single quiz request."""

    def __init__(
        self,
        fact_repository: FactRepository,
        web_repository: WebRepository,
        llm_client: LLMClient,
        cache: QuizCache | None = None,
        rate_limiter: RateLimiter | None = None,
        max_context_tokens: int = 1500,
        prompt_version: str = "v2",
        cache_ttl_seconds: int = 6 * 60 * 60,
        local_top_k: int = 3,
        web_top_k: int = 3,
    ) -> None:
        self._fact_repository = fact_repository
        self._web_repository = web_repository
        self._llm_client = llm_client
        self._cache = cache
        self._rate_limiter = rate_limiter
        self._max_context_tokens = max_context_tokens
        self._prompt_version = prompt_version
        self._cache_ttl_seconds = cache_ttl_seconds
        self._local_top_k = local_top_k
        self._web_top_k = web_top_k

    def generate(self, request: GenerationRequest) -> Quiz:
        """
        Runs the full pipeline for a single GenerationRequest and returns a
        validated Quiz. Wraps the whole call in a request_scope so every
        log line across every layer carries the same request_id.
        """
        with request_scope() as request_id:
            pipeline_start = time.monotonic()
            logger.info(
                "quiz_request_started",
                sport=request.sport.value,
                difficulty=request.difficulty.value,
                question_count=request.question_count,
            )

            if self._rate_limiter is not None:
                try:
                    self._rate_limiter.check(identity="default")
                except RateLimitExceededError:
                    _audit(request_id, request, outcome="rate_limited")
                    raise

            if self._cache is not None:
                cached = self._cache.get(request.sport, request.difficulty, self._prompt_version)
                if cached is not None:
                    logger.info("quiz_request_served_from_cache", request_id=request_id)
                    _audit(request_id, request, outcome="cache_hit")
                    return cached

            facts = self._retrieve_local(request)
            snippets = self._retrieve_web(request)

            if not facts and not snippets:
                _audit(request_id, request, outcome="no_context_available")
                raise NoContextAvailableError(
                    "pipeline", "both local and web retrieval returned no usable context."
                )

            merge_start = time.monotonic()
            merged = merge_and_deduplicate(facts, snippets)
            logger.info(
                "merge_stage_completed",
                duration_ms=round((time.monotonic() - merge_start) * 1000, 1),
            )

            compress_start = time.monotonic()
            compressed = compress_context(merged, max_tokens=self._max_context_tokens)
            logger.info(
                "compression_stage_completed",
                duration_ms=round((time.monotonic() - compress_start) * 1000, 1),
                compressed_chars=len(compressed),
            )

            generation_start = time.monotonic()
            try:
                quiz = generate_quiz(
                    request=request,
                    compressed_context=compressed,
                    prompt_version=self._prompt_version,
                    llm_client=self._llm_client,
                )
            except Exception:
                _audit(request_id, request, outcome="generation_failed")
                raise
            quiz = _attribute_sources(quiz, merged)
            logger.info(
                "generation_stage_completed",
                duration_ms=round((time.monotonic() - generation_start) * 1000, 1),
            )

            if self._cache is not None:
                self._cache.set(
                    request.sport,
                    request.difficulty,
                    self._prompt_version,
                    quiz,
                    self._cache_ttl_seconds,
                )

            logger.info(
                "quiz_request_completed",
                total_duration_ms=round((time.monotonic() - pipeline_start) * 1000, 1),
            )
            _audit(request_id, request, outcome="success")
            return quiz

    def _retrieve_local(self, request: GenerationRequest) -> list[RetrievedFact]:
        query = build_local_query(request.sport, request.difficulty)
        start = time.monotonic()
        try:
            facts = self._fact_repository.query(
                sport=request.sport.value, query_text=query, top_k=self._local_top_k
            )
            logger.info(
                "local_retrieval_completed",
                duration_ms=round((time.monotonic() - start) * 1000, 1),
                result_count=len(facts),
            )
            return facts
        except RetrievalError as exc:
            logger.warning("local_retrieval_failed_continuing", error=str(exc))
            return []

    def _retrieve_web(self, request: GenerationRequest) -> list[WebSnippet]:
        query = build_web_query(request.sport)
        start = time.monotonic()
        try:
            snippets = self._web_repository.search(
                sport=request.sport.value, query_text=query, top_k=self._web_top_k
            )
            logger.info(
                "web_retrieval_completed",
                duration_ms=round((time.monotonic() - start) * 1000, 1),
                result_count=len(snippets),
            )
            return snippets
        except RetrievalError as exc:
            logger.warning("web_retrieval_failed_continuing", error=str(exc))
            return []
