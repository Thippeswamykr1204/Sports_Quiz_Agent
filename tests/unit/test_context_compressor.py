"""Unit tests for token-budget context compression."""

from src.generation.context_compressor import compress_context, estimate_tokens
from src.schemas.retrieval import MergedContext, RetrievedFact, WebSnippet


def _fact(text: str, relevance: float) -> RetrievedFact:
    return RetrievedFact(text=text, sport="Cricket", relevance_score=relevance)


def _snippet(text: str, relevance: float) -> WebSnippet:
    return WebSnippet(title="Some Article", text=text, url="https://x.com", relevance_score=relevance)


def test_compress_empty_context_returns_empty_string():
    merged = MergedContext(items=[], local_count=0, web_count=0)

    result = compress_context(merged, max_tokens=1000)

    assert result == ""


def test_compress_includes_all_items_when_within_budget():
    merged = MergedContext(
        items=[_fact("Short fact one.", 0.9), _fact("Short fact two.", 0.8)],
        local_count=2,
        web_count=0,
    )

    result = compress_context(merged, max_tokens=1000)

    assert "Short fact one." in result
    assert "Short fact two." in result


def test_compress_prioritizes_higher_relevance_items():
    merged = MergedContext(
        items=[
            _fact("LOW_RELEVANCE_FACT " * 50, 0.1),
            _fact("HIGH_RELEVANCE_FACT", 0.95),
        ],
        local_count=2,
        web_count=0,
    )

    # Small budget forces a choice — the high relevance one must survive.
    result = compress_context(merged, max_tokens=15)

    assert "HIGH_RELEVANCE_FACT" in result


def test_compress_always_includes_at_least_one_item_even_if_over_budget():
    merged = MergedContext(
        items=[_fact("A" * 2000, 0.9)],
        local_count=1,
        web_count=0,
    )

    result = compress_context(merged, max_tokens=1)

    assert result != ""


def test_compress_labels_local_and_web_items_differently():
    merged = MergedContext(
        items=[_fact("Local fact text.", 0.9), _snippet("Web snippet text.", 0.8)],
        local_count=1,
        web_count=1,
    )

    result = compress_context(merged, max_tokens=1000)

    assert "[Local KB]" in result
    assert "[Web:" in result


def test_estimate_tokens_scales_with_length():
    short_estimate = estimate_tokens("hi")
    long_estimate = estimate_tokens("hi " * 100)

    assert long_estimate > short_estimate
