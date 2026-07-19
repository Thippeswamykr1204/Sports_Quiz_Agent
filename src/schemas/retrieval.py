"""
Retrieval-layer contracts.

Both retrievers (local ChromaDB, live DuckDuckGo) return these typed
objects rather than raw dicts/strings, so the merge/dedupe/compression
steps downstream can rely on a stable shape and each item carries its own
provenance for source-attributed UI rendering later.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    """Where a piece of retrieved context came from — drives the UI source chips."""

    LOCAL_KB = "local_kb"
    WEB = "web"


class RetrievedFact(BaseModel):
    """A single fact returned by the local ChromaDB retriever."""

    text: str = Field(..., min_length=1)
    sport: str
    relevance_score: float = Field(
        ..., ge=0.0, le=1.0, description="1.0 = most relevant, from vector distance."
    )
    source_type: SourceType = SourceType.LOCAL_KB


class WebSnippet(BaseModel):
    """A single search-result snippet returned by the live web retriever."""

    title: str
    text: str = Field(..., min_length=1)
    url: str | None = None
    relevance_score: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "1.0 = most relevant. Search engines already rank results, so this "
            "defaults to a rank-derived estimate rather than a real similarity score."
        ),
    )
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_type: SourceType = SourceType.WEB

    @field_validator("url")
    @classmethod
    def _only_http_https(cls, v: str | None) -> str | None:
        """
        Drops any URL that isn't http(s) rather than raising - a search
        result with a weird/unsafe scheme (e.g. "javascript:...") should be
        treated as "no link available", not fail the whole snippet. This
        URL is later rendered as a real, clickable markdown link
        (src/ui/components.py), so an unvalidated scheme here would be a
        click-through XSS vector, not just a display glitch.
        """
        if v is None:
            return None
        if not (v.startswith("http://") or v.startswith("https://")):
            return None
        return v


class MergedContext(BaseModel):
    """
    Output of the Merge + Deduplicate step: a single ordered list of
    context items (facts and snippets normalized to one shape) ready for
    context compression, plus bookkeeping for observability.
    """

    items: list[RetrievedFact | WebSnippet]
    local_count: int
    web_count: int
    deduplicated_count: int = Field(
        default=0, description="Number of near-duplicate items dropped during merge."
    )

    @property
    def is_empty(self) -> bool:
        return len(self.items) == 0