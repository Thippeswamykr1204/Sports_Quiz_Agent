"""
AI Transparency Mode - pipeline trace capture.

Records what the generation pipeline actually did for one request: each
named stage with real status/duration, retrieved context with real
similarity scores, token usage when the provider exposes it, retry
count, chunk count, sources used. Nothing here is synthesized - a field
that can't be measured is None/omitted and the UI must say so, not
invent a number.

Traces live in a small bounded in-memory dict keyed by request_id (same
process-lifetime tradeoff as src/core/metrics.py - flagged there and
here as a Future Enhancement to persist if this needs to survive a
restart or scale to multiple workers).
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class StageTrace:
    name: str
    status: str  # "ok" | "failed" | "skipped"
    duration_ms: float
    detail: str = ""


@dataclass
class RetrievedItem:
    """One retrieved context item with its real similarity/relevance score."""

    label: str
    source_type: str  # "local_kb" | "web"
    relevance_score: float
    excerpt: str
    url: str | None = None


@dataclass
class PipelineTrace:
    request_id: str
    prompt_version: str
    stages: list[StageTrace] = field(default_factory=list)
    retrieved_items: list[RetrievedItem] = field(default_factory=list)
    chunks_used: int = 0
    sources_used: list[str] = field(default_factory=list)
    confidence_score: float | None = None
    generation_time_ms: float | None = None
    retry_count: int = 0
    token_usage: dict[str, int] | None = None  # None means "provider didn't report it"

    @property
    def total_duration_ms(self) -> float:
        return sum(s.duration_ms for s in self.stages)


class TraceBuilder:
    """Accumulates a PipelineTrace across one generate() call."""

    def __init__(self, request_id: str, prompt_version: str) -> None:
        self.trace = PipelineTrace(request_id=request_id, prompt_version=prompt_version)

    @contextmanager
    def stage(self, name: str, detail: str = "") -> Iterator[None]:
        start = time.monotonic()
        try:
            yield
            self.trace.stages.append(
                StageTrace(name=name, status="ok", duration_ms=(time.monotonic() - start) * 1000, detail=detail)
            )
        except Exception as exc:
            self.trace.stages.append(
                StageTrace(
                    name=name,
                    status="failed",
                    duration_ms=(time.monotonic() - start) * 1000,
                    detail=str(exc),
                )
            )
            raise

    def skip_stage(self, name: str, detail: str) -> None:
        self.trace.stages.append(StageTrace(name=name, status="skipped", duration_ms=0.0, detail=detail))


class TraceStore:
    """Bounded in-memory {request_id: PipelineTrace} - see module docstring."""

    def __init__(self, max_entries: int = 50) -> None:
        self._max_entries = max_entries
        self._traces: dict[str, PipelineTrace] = {}
        self._order: list[str] = []

    def put(self, trace: PipelineTrace) -> None:
        self._traces[trace.request_id] = trace
        self._order.append(trace.request_id)
        while len(self._order) > self._max_entries:
            oldest = self._order.pop(0)
            self._traces.pop(oldest, None)

    def get(self, request_id: str) -> PipelineTrace | None:
        return self._traces.get(request_id)