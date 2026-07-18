"""
Merge + Deduplicate step of the retrieval pipeline.

Combines RetrievedFact and WebSnippet lists into a single MergedContext,
dropping near-duplicate items (e.g. the same historical fact showing up
in both the local KB and a web snippet) so context compression doesn't
waste its token budget on repeated information.
"""

import re

from src.core.logging import get_logger
from src.schemas.retrieval import MergedContext, RetrievedFact, WebSnippet

logger = get_logger("merge")

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Casefolds and collapses whitespace so near-identical text compares equal."""
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


def merge_and_deduplicate(
    facts: list[RetrievedFact],
    snippets: list[WebSnippet],
) -> MergedContext:
    """
    Combines local facts and web snippets into one deduplicated list.

    When two items normalize to (near-)identical text, the one with the
    higher relevance_score is kept. Order of the input lists does not
    matter — output is not yet sorted here, that's context_compressor's job.
    """
    all_items: list[RetrievedFact | WebSnippet] = [*facts, *snippets]

    seen_normalized: dict[str, RetrievedFact | WebSnippet] = {}
    duplicates_dropped = 0

    for item in all_items:
        key = _normalize(item.text)
        existing = seen_normalized.get(key)

        if existing is None:
            seen_normalized[key] = item
            continue

        duplicates_dropped += 1
        if item.relevance_score > existing.relevance_score:
            seen_normalized[key] = item

    merged = MergedContext(
        items=list(seen_normalized.values()),
        local_count=len(facts),
        web_count=len(snippets),
        deduplicated_count=duplicates_dropped,
    )

    logger.info(
        "context_merged",
        local_count=merged.local_count,
        web_count=merged.web_count,
        deduplicated_count=merged.deduplicated_count,
        final_item_count=len(merged.items),
    )
    return merged
