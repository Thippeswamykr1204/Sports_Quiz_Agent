"""
Unit tests for ChromaFactRepository.

Chroma itself is mocked out — these tests verify our wrapping logic
(seed validation, distance-to-relevance mapping, error translation), not
ChromaDB's internals. Integration-level "does chroma actually work" is
covered separately (see tests/integration).
"""

import json

import pytest

from src.core.exceptions import DataLoadError, RetrievalError
from src.repositories.fact_repository import ChromaFactRepository, _load_seed_facts
from src.schemas.retrieval import SourceType


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A ChromaFactRepository with a fake underlying collection."""
    instance = ChromaFactRepository.__new__(ChromaFactRepository)
    instance._persist_dir = tmp_path
    instance._collection = FakeCollection()
    return instance


class FakeCollection:
    def __init__(self):
        self._docs = []
        self._metas = []
        self._ids = []

    def count(self):
        return len(self._docs)

    def add(self, documents, metadatas, ids):
        self._docs.extend(documents)
        self._metas.extend(metadatas)
        self._ids.extend(ids)

    def query(self, query_texts, n_results, where):
        sport = where["sport"]
        matches = [
            (doc, 0.1 * i)
            for i, (doc, meta) in enumerate(zip(self._docs, self._metas))
            if meta["sport"] == sport
        ][:n_results]
        return {
            "documents": [[m[0] for m in matches]],
            "distances": [[m[1] for m in matches]],
        }


# --- Seed file loading & validation ---

def test_load_seed_facts_valid_file(tmp_path):
    seed_path = tmp_path / "facts.json"
    seed_path.write_text(json.dumps([{"sport": "Cricket", "fact": "Test fact."}]))

    facts = _load_seed_facts(seed_path)

    assert len(facts) == 1
    assert facts[0].sport == "Cricket"


def test_load_seed_facts_missing_file_raises(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"

    with pytest.raises(DataLoadError, match="not found"):
        _load_seed_facts(missing_path)


def test_load_seed_facts_invalid_json_raises(tmp_path):
    seed_path = tmp_path / "facts.json"
    seed_path.write_text("{not valid json")

    with pytest.raises(DataLoadError, match="not valid JSON"):
        _load_seed_facts(seed_path)


def test_load_seed_facts_not_a_list_raises(tmp_path):
    seed_path = tmp_path / "facts.json"
    seed_path.write_text(json.dumps({"sport": "Cricket", "fact": "oops, not a list"}))

    with pytest.raises(DataLoadError, match="must contain a JSON array"):
        _load_seed_facts(seed_path)


def test_load_seed_facts_missing_field_raises(tmp_path):
    seed_path = tmp_path / "facts.json"
    seed_path.write_text(json.dumps([{"sport": "Cricket"}]))  # missing "fact"

    with pytest.raises(DataLoadError, match="invalid entries"):
        _load_seed_facts(seed_path)


# --- Seeding behavior ---

def test_seed_inserts_when_empty(repo, tmp_path):
    seed_path = tmp_path / "facts.json"
    seed_path.write_text(
        json.dumps(
            [
                {"sport": "Cricket", "fact": "Fact one."},
                {"sport": "Football", "fact": "Fact two."},
            ]
        )
    )

    inserted = repo.seed(seed_path)

    assert inserted == 2
    assert repo.is_seeded()


def test_seed_is_idempotent(repo, tmp_path):
    seed_path = tmp_path / "facts.json"
    seed_path.write_text(json.dumps([{"sport": "Cricket", "fact": "Fact one."}]))

    first = repo.seed(seed_path)
    second = repo.seed(seed_path)

    assert first == 1
    assert second == 0  # already seeded, no-op


# --- Querying & relevance mapping ---

def test_query_returns_retrieved_facts_for_matching_sport(repo, tmp_path):
    seed_path = tmp_path / "facts.json"
    seed_path.write_text(
        json.dumps(
            [
                {"sport": "Cricket", "fact": "Cricket fact A."},
                {"sport": "Cricket", "fact": "Cricket fact B."},
                {"sport": "Football", "fact": "Football fact."},
            ]
        )
    )
    repo.seed(seed_path)

    results = repo.query(sport="Cricket", query_text="history", top_k=5)

    assert len(results) == 2
    assert all(r.sport == "Cricket" for r in results)
    assert all(r.source_type == SourceType.LOCAL_KB for r in results)


def test_query_relevance_score_within_bounds(repo, tmp_path):
    seed_path = tmp_path / "facts.json"
    seed_path.write_text(json.dumps([{"sport": "Tennis", "fact": "Tennis fact."}]))
    repo.seed(seed_path)

    results = repo.query(sport="Tennis", query_text="grand slam", top_k=1)

    assert len(results) == 1
    assert 0.0 <= results[0].relevance_score <= 1.0


def test_query_wraps_collection_errors_as_retrieval_error(repo):
    def _boom(*args, **kwargs):
        raise RuntimeError("chroma exploded")

    repo._collection.query = _boom

    with pytest.raises(RetrievalError, match="local_kb"):
        repo.query(sport="Cricket", query_text="anything", top_k=3)
