"""
Local knowledge-base repository (Repository Pattern).

FactRepository is the interface the service layer depends on.
ChromaFactRepository is the current implementation. Swapping to a
different vector store later means writing a new class that satisfies
this Protocol — no changes anywhere else in the codebase.
"""

import json
from pathlib import Path
from typing import Protocol

import chromadb
from chromadb.utils import embedding_functions
from pydantic import ValidationError

from src.core.exceptions import DataLoadError, RetrievalError
from src.core.logging import get_logger
from src.schemas.retrieval import RetrievedFact, SourceType
from src.schemas.seed_data import SeedFact

logger = get_logger("fact_repository")

_COLLECTION_NAME = "sports_history"


class FactRepository(Protocol):
    """Interface for retrieving locally stored facts relevant to a query."""

    def query(self, sport: str, query_text: str, top_k: int) -> list[RetrievedFact]:
        """Returns up to top_k facts for the given sport, ranked by relevance."""
        ...

    def is_seeded(self) -> bool:
        """Returns True if the underlying store already has data."""
        ...

    def seed(self, seed_path: Path) -> int:
        """Loads and inserts seed data if the store is empty. Returns count inserted."""
        ...


def _load_seed_facts(seed_path: Path) -> list[SeedFact]:
    """Reads and validates the raw JSON seed file, raising DataLoadError on failure."""
    if not seed_path.exists():
        raise DataLoadError(f"Seed data file not found at {seed_path}")

    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataLoadError(f"Seed file at {seed_path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, list):
        raise DataLoadError(f"Seed file at {seed_path} must contain a JSON array.")

    try:
        return [SeedFact.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise DataLoadError(f"Seed file at {seed_path} has invalid entries: {exc}") from exc


class ChromaFactRepository:
    """ChromaDB-backed implementation of FactRepository."""

    def __init__(self, persist_dir: Path) -> None:
        self._persist_dir = persist_dir
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=self._embedding_fn,
        )

    def is_seeded(self) -> bool:
        try:
            return self._collection.count() > 0
        except Exception as exc:  # pragma: no cover - defensive, chroma internals
            raise RetrievalError("local_kb", f"failed to check collection state: {exc}") from exc

    def seed(self, seed_path: Path) -> int:
        if self.is_seeded():
            logger.info("local_kb_already_seeded", count=self._collection.count())
            return 0

        facts = _load_seed_facts(seed_path)

        documents = [f.fact for f in facts]
        metadatas = [{"sport": f.sport} for f in facts]
        ids = [f"fact_{i}" for i in range(len(facts))]

        try:
            self._collection.add(documents=documents, metadatas=metadatas, ids=ids)
        except Exception as exc:
            raise RetrievalError("local_kb", f"failed to insert seed data: {exc}") from exc

        logger.info("local_kb_seeded", count=len(facts))
        return len(facts)

    def query(self, sport: str, query_text: str, top_k: int = 3) -> list[RetrievedFact]:
        try:
            results = self._collection.query(
                query_texts=[query_text],
                n_results=top_k,
                where={"sport": sport},
            )
        except Exception as exc:
            raise RetrievalError("local_kb", f"query failed: {exc}") from exc

        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0] if results.get("distances") else []

        facts: list[RetrievedFact] = []
        for idx, doc in enumerate(documents):
            # Chroma returns a distance (lower = closer); convert to a 0..1
            # relevance score where 1.0 = most relevant. Clamp defensively
            # since distance metrics/ranges can vary by embedding function.
            distance = distances[idx] if idx < len(distances) else 1.0
            relevance = max(0.0, min(1.0, 1.0 - distance))
            facts.append(
                RetrievedFact(
                    text=doc,
                    sport=sport,
                    relevance_score=relevance,
                    source_type=SourceType.LOCAL_KB,
                )
            )

        logger.info("local_kb_query_completed", sport=sport, result_count=len(facts))
        return facts
