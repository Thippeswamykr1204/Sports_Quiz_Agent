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
from src.core.metrics import ServiceMetrics
from src.core.rate_limiter import RateLimiter
from src.core.request_context import request_scope
from src.core.tracing import PipelineTrace, RetrievedItem, TraceBuilder, TraceStore
from src.repositories.attempt_repository import AttemptRepository
from src.services.analytics_service import AnalyticsService
from src.services.history_service import HistoryService
from src.services.knowledge_service import KnowledgeService
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
        history_service: HistoryService | None = None,
        attempt_repository: AttemptRepository | None = None,
        analytics_service: AnalyticsService | None = None,
        metrics: ServiceMetrics | None = None,
        knowledge_service: KnowledgeService | None = None,
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
        self._metrics = metrics if metrics is not None else ServiceMetrics()
        self._history_service = history_service
        self._trace_store = TraceStore()
        self._attempt_repository = attempt_repository
        self._analytics_service = analytics_service
        self._knowledge_service = knowledge_service

    def get_knowledge_service(self) -> KnowledgeService | None:
        return self._knowledge_service

    def get_trace(self, request_id: str) -> PipelineTrace | None:
        """Real per-request pipeline trace for AI Transparency Mode, or None if expired/unknown."""
        return self._trace_store.get(request_id)

    def get_attempt_repository(self) -> AttemptRepository | None:
        return self._attempt_repository

    def get_analytics_service(self) -> AnalyticsService | None:
        return self._analytics_service

    def get_metrics(self) -> ServiceMetrics:
        """Real, process-lifetime counters - see src/core/metrics.py."""
        return self._metrics

    def get_kb_size(self) -> int | None:
        """Real fact count from the vector store, or None if it can't be reached."""
        try:
            return self._fact_repository.count()
        except Exception:
            return None

    def get_history_service(self) -> HistoryService | None:
        return self._history_service

    def health_check(self) -> dict[str, tuple[str, str]]:
        """
        Returns {component: (status, detail)} for Home/Health Status cards.

        status is one of "ok", "degraded", "unknown" - never fabricated.
        Components this app can genuinely probe cheaply get a real check;
        components it can't (a live Gemini call costs quota/latency on
        every dashboard render) are marked "unknown" with a note, per the
        "don't fake data" rule, rather than shown as a fake green light.
        """
        results: dict[str, tuple[str, str]] = {}

        try:
            count = self._fact_repository.is_seeded()
            results["Vector Database"] = ("ok", "Connected, seeded" if count else "Connected, empty")
        except Exception as exc:
            results["Vector Database"] = ("degraded", f"Unreachable: {exc}")

        if self._cache is not None:
            results["Cache"] = ("ok", "Disk cache initialized")
        else:
            results["Cache"] = ("degraded", "No cache configured")

        # Gemini: checking API key presence is real and cheap; a live
        # completion call is not done here (would cost quota/latency on
        # every page load). Future Enhancement: a periodic background
        # ping (e.g. every N minutes) instead of per-request.
        results["Gemini"] = (
            "unknown",
            "Client configured — liveness not probed per request (see health_check docstring)",
        )

        results["System"] = ("ok", f"Uptime {int(self._metrics.uptime_seconds)}s")

        return results

    def generate(self, request: GenerationRequest) -> Quiz:
        """
        Runs the full pipeline for a single GenerationRequest and returns a
        validated Quiz. Wraps the whole call in a request_scope so every
        log line across every layer carries the same request_id.
        """
        with request_scope() as request_id:
            pipeline_start = time.monotonic()
            builder = TraceBuilder(request_id=request_id, prompt_version=self._prompt_version)
            logger.info(
                "quiz_request_started",
                sport=request.sport.value,
                difficulty=request.difficulty.value,
                question_count=request.question_count,
            )

            with builder.stage("Validation", detail="GenerationRequest (Sport/Difficulty enums, question_count)"):
                pass  # request is already a validated Pydantic model by the time it reaches here

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
                    self._metrics.record_cache_hit()
                    builder.skip_stage("Retrieval", "Served from cache - retrieval not run")
                    builder.skip_stage("Ranking", "Served from cache - ranking not run")
                    builder.skip_stage("Context Building", "Served from cache - compression not run")
                    builder.skip_stage("Prompt Generation", "Served from cache")
                    builder.skip_stage("Gemini Response", "Served from cache")
                    builder.skip_stage("JSON Parsing", "Served from cache")
                    builder.trace.confidence_score = (
                        sum(q.confidence for q in cached.questions) / len(cached.questions)
                    )
                    builder.trace.generation_time_ms = cached.generation_time_ms
                    builder.trace.sources_used = sorted(
                        {s.label for q in cached.questions for s in q.sources}
                    )
                    with builder.stage("Completed", detail="Served from cache"):
                        pass
                    self._trace_store.put(builder.trace)
                    return cached

            with builder.stage("Retrieval", detail="Local KB + web search, run in sequence") as _:
                facts = self._retrieve_local(request)
                snippets = self._retrieve_web(request)

            if not facts and not snippets:
                _audit(request_id, request, outcome="no_context_available")
                with builder.stage("Completed", detail="Failed - no context available"):
                    pass
                self._trace_store.put(builder.trace)
                raise NoContextAvailableError(
                    "pipeline", "both local and web retrieval returned no usable context."
                )

            merge_start = time.monotonic()
            with builder.stage("Ranking", detail="Merge local + web, dedupe, sort by relevance"):
                merged = merge_and_deduplicate(facts, snippets)
            logger.info(
                "merge_stage_completed",
                duration_ms=round((time.monotonic() - merge_start) * 1000, 1),
            )

            for item in sorted(merged.items, key=lambda i: i.relevance_score, reverse=True):
                if isinstance(item, RetrievedFact):
                    builder.trace.retrieved_items.append(
                        RetrievedItem(
                            label=f"Local KB — {item.sport}",
                            source_type="local_kb",
                            relevance_score=item.relevance_score,
                            excerpt=item.text,
                        )
                    )
                elif isinstance(item, WebSnippet):
                    builder.trace.retrieved_items.append(
                        RetrievedItem(
                            label=item.title,
                            source_type="web",
                            relevance_score=item.relevance_score,
                            excerpt=item.text,
                            url=item.url,
                        )
                    )

            compress_start = time.monotonic()
            with builder.stage("Context Building", detail="Compress merged context to token budget"):
                compressed = compress_context(merged, max_tokens=self._max_context_tokens)
            logger.info(
                "compression_stage_completed",
                duration_ms=round((time.monotonic() - compress_start) * 1000, 1),
                compressed_chars=len(compressed),
            )
            builder.trace.chunks_used = len(merged.items)

            generation_start = time.monotonic()
            try:
                quiz = generate_quiz(
                    request=request,
                    compressed_context=compressed,
                    prompt_version=self._prompt_version,
                    llm_client=self._llm_client,
                    trace_builder=builder,
                )
            except Exception:
                _audit(request_id, request, outcome="generation_failed")
                with builder.stage("Completed", detail="Failed - see earlier stage for cause"):
                    pass
                self._trace_store.put(builder.trace)
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
            duration_ms = (time.monotonic() - pipeline_start) * 1000
            self._metrics.record_fresh_generation(duration_ms)
            quiz = quiz.model_copy(update={"generation_time_ms": duration_ms})

            builder.trace.confidence_score = sum(q.confidence for q in quiz.questions) / len(quiz.questions)
            builder.trace.generation_time_ms = duration_ms
            builder.trace.sources_used = sorted({s.label for q in quiz.questions for s in q.sources})
            with builder.stage("Completed"):
                pass
            self._trace_store.put(builder.trace)

            if self._history_service is not None:
                try:
                    self._history_service.record(
                        quiz,
                        chunks_used=builder.trace.chunks_used,
                        sources_count=len(quiz.questions[0].sources) if quiz.questions[0].sources else 0,
                    )
                except Exception as exc:  # pragma: no cover - history is best-effort
                    logger.warning("history_persist_failed", error=str(exc))

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