"""Unit tests for the merge + deduplicate step."""

from src.schemas.retrieval import RetrievedFact, WebSnippet
from src.services.merge import merge_and_deduplicate


def _fact(text: str, relevance: float = 0.8) -> RetrievedFact:
    return RetrievedFact(text=text, sport="Cricket", relevance_score=relevance)


def _snippet(text: str, relevance: float = 0.7) -> WebSnippet:
    return WebSnippet(title="Article", text=text, url="https://x.com", relevance_score=relevance)


def test_merge_combines_facts_and_snippets():
    merged = merge_and_deduplicate(
        facts=[_fact("Fact A"), _fact("Fact B")],
        snippets=[_snippet("Snippet A")],
    )

    assert len(merged.items) == 3
    assert merged.local_count == 2
    assert merged.web_count == 1


def test_merge_drops_exact_duplicates():
    merged = merge_and_deduplicate(
        facts=[_fact("Same fact text.")],
        snippets=[_snippet("Same fact text.")],
    )

    assert len(merged.items) == 1
    assert merged.deduplicated_count == 1


def test_merge_dedup_is_case_and_whitespace_insensitive():
    merged = merge_and_deduplicate(
        facts=[_fact("Uruguay Won   The World Cup")],
        snippets=[_snippet("uruguay won the world cup")],
    )

    assert len(merged.items) == 1


def test_merge_keeps_higher_relevance_item_on_duplicate():
    low = _fact("Duplicate text here.", relevance=0.3)
    high = _snippet("Duplicate text here.", relevance=0.95)

    merged = merge_and_deduplicate(facts=[low], snippets=[high])

    assert len(merged.items) == 1
    assert merged.items[0].relevance_score == 0.95


def test_merge_with_no_input_returns_empty_context():
    merged = merge_and_deduplicate(facts=[], snippets=[])

    assert merged.is_empty
    assert merged.deduplicated_count == 0


def test_merge_preserves_distinct_items_untouched():
    merged = merge_and_deduplicate(
        facts=[_fact("Unique fact one."), _fact("Unique fact two.")],
        snippets=[_snippet("Unique web snippet.")],
    )

    assert len(merged.items) == 3
    assert merged.deduplicated_count == 0
