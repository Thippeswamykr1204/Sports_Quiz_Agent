"""
Local knowledge-base repository (Repository Pattern).

FactRepository is the interface the service layer depends on.
ChromaFactRepository is the current implementation. Swapping to a
different vector store later means writing a new class that satisfies
this Protocol — no changes anywhere else in the codebase.
"""

import json
from dataclasses import dataclass
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
_DEFAULT_SOURCE = "Local Knowledge Base"


@dataclass(frozen=True)
class KnowledgeChunk:
    """
    One explorable KB entry - the Explorer's unit of display.

    embedding_id is the vector store's opaque identifier (safe to show -
    it's just a handle, not an implementation detail like the collection
    name, persist path, or the embedding vector itself, none of which are
    exposed here on purpose).
    """

    embedding_id: str
    text: str
    sport: str
    tags: list[str]
    date: str | None
    source: str
    similarity_score: float | None  # None in browse mode, set in search mode


@dataclass(frozen=True)
class ChunkFilter:
    """All fields optional - None/empty means "don't filter on this"."""

    sport: str | None = None
    source: str | None = None
    tag: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    search_text: str | None = None


class FactRepository(Protocol):
    """Interface for retrieving locally stored facts relevant to a query."""

    def query(self, sport: str, query_text: str, top_k: int) -> list[RetrievedFact]:
        """Returns up to top_k facts for the given sport, ranked by relevance."""
        ...

    def is_seeded(self) -> bool:
        """Returns True if the underlying store already has data."""
        ...

    def count(self) -> int:
        """Returns the number of facts currently stored (for KB-size stat cards)."""
        ...

    def seed(self, seed_path: Path) -> int:
        """Loads and inserts seed data if the store is empty. Returns count inserted."""
        ...

    def browse(self, filters: ChunkFilter, offset: int, limit: int) -> tuple[list[KnowledgeChunk], int]:
        """Returns (page of chunks, total matching count) for Explorer's Browse mode."""
        ...

    def semantic_search(self, query_text: str, filters: ChunkFilter, limit: int) -> list[KnowledgeChunk]:
        """Returns chunks ranked by real embedding similarity to query_text."""
        ...

    def filter_options(self) -> dict[str, list[str]]:
        """Returns real, derived-from-data values for each filterable field."""
        ...

    def clear(self) -> int:
        """Deletes all stored facts. Returns the number of entries removed. Use with seed() to rebuild."""
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

    def count(self) -> int:
        try:
            return self._collection.count()
        except Exception as exc:  # pragma: no cover - defensive, chroma internals
            raise RetrievalError("local_kb", f"failed to count collection: {exc}") from exc

    def seed(self, seed_path: Path) -> int:
        if self.is_seeded():
            logger.info("local_kb_already_seeded", count=self._collection.count())
            return 0

        facts = _load_seed_facts(seed_path)

        documents = [f.fact for f in facts]
        metadatas = [
            {
                "sport": f.sport,
                "tags": ",".join(f.tags),  # Chroma metadata values must be scalar - store as CSV
                "date": f.date or "",
                "source": f.source or _DEFAULT_SOURCE,
            }
            for f in facts
        ]
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

    def _row_to_chunk(self, chunk_id: str, document: str, metadata: dict, similarity_score: float | None) -> KnowledgeChunk:
        tags_raw = metadata.get("tags", "") or ""
        return KnowledgeChunk(
            embedding_id=chunk_id,
            text=document,
            sport=metadata.get("sport", "Unknown"),
            tags=[t for t in tags_raw.split(",") if t],
            date=metadata.get("date") or None,
            source=metadata.get("source") or _DEFAULT_SOURCE,
            similarity_score=similarity_score,
        )

    def _build_where_clause(self, filters: "ChunkFilter") -> dict | None:
        """
        Chroma `where` only supports exact-match/scalar comparisons - tag
        (substring within a CSV string) and free-text search are applied
        in Python after fetching the sport/source/date-narrowed candidate
        set. Fine at this corpus's scale (tens to low hundreds of facts);
        a KB large enough to make that slow would need tag/text search
        pushed into the store itself (Future Enhancement).
        """
        clauses = []
        if filters.sport:
            clauses.append({"sport": filters.sport})
        if filters.source:
            clauses.append({"source": filters.source})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def _matches_python_side_filters(self, metadata: dict, document: str, filters: "ChunkFilter") -> bool:
        if filters.tag:
            tags = (metadata.get("tags") or "").split(",")
            if filters.tag not in tags:
                return False
        if filters.date_from or filters.date_to:
            date_value = metadata.get("date") or ""
            if not date_value:
                return False
            if filters.date_from and date_value < filters.date_from:
                return False
            if filters.date_to and date_value > filters.date_to:
                return False
        if filters.search_text:
            needle = filters.search_text.lower()
            if needle not in document.lower():
                return False
        return True

    def browse(self, filters: "ChunkFilter", offset: int = 0, limit: int = 20) -> tuple[list["KnowledgeChunk"], int]:
        try:
            where = self._build_where_clause(filters)
            results = self._collection.get(
                where=where, include=["documents", "metadatas"]
            )
        except Exception as exc:
            raise RetrievalError("local_kb", f"browse failed: {exc}") from exc

        ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        matched: list[KnowledgeChunk] = []
        for chunk_id, doc, meta in zip(ids, documents, metadatas):
            if self._matches_python_side_filters(meta, doc, filters):
                matched.append(self._row_to_chunk(chunk_id, doc, meta, similarity_score=None))

        matched.sort(key=lambda c: c.embedding_id)
        total = len(matched)
        return matched[offset : offset + limit], total

    def semantic_search(self, query_text: str, filters: "ChunkFilter", limit: int = 20) -> list["KnowledgeChunk"]:
        try:
            where = self._build_where_clause(filters)
            # Over-fetch since tag/date/text filters are applied after the
            # vector search - real similarity scores still come straight
            # from Chroma, filtering just narrows which of those real
            # results are shown.
            results = self._collection.query(
                query_texts=[query_text],
                n_results=max(limit * 4, 20),
                where=where,
            )
        except Exception as exc:
            raise RetrievalError("local_kb", f"semantic search failed: {exc}") from exc

        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0] if results.get("distances") else []

        chunks: list[KnowledgeChunk] = []
        for idx, (chunk_id, doc, meta) in enumerate(zip(ids, documents, metadatas)):
            if not self._matches_python_side_filters(meta, doc, filters):
                continue
            distance = distances[idx] if idx < len(distances) else 1.0
            similarity = max(0.0, min(1.0, 1.0 - distance))
            chunks.append(self._row_to_chunk(chunk_id, doc, meta, similarity_score=similarity))
            if len(chunks) >= limit:
                break

        return chunks

    def filter_options(self) -> dict[str, list[str]]:
        """Real, derived-from-stored-data filter values - never a hardcoded guess."""
        try:
            results = self._collection.get(include=["metadatas"])
        except Exception as exc:
            raise RetrievalError("local_kb", f"failed to read filter options: {exc}") from exc

        metadatas = results.get("metadatas", [])
        sports = sorted({m.get("sport") for m in metadatas if m.get("sport")})
        sources = sorted({m.get("source") for m in metadatas if m.get("source")})
        tags = sorted({t for m in metadatas for t in (m.get("tags") or "").split(",") if t})

        return {"sports": sports, "sources": sources, "tags": tags}

    def clear(self) -> int:
        try:
            existing = self._collection.get(include=[])
            ids = existing.get("ids", [])
            if ids:
                self._collection.delete(ids=ids)
        except Exception as exc:
            raise RetrievalError("local_kb", f"failed to clear collection: {exc}") from exc
        logger.info("local_kb_cleared", count=len(ids))
        return len(ids)