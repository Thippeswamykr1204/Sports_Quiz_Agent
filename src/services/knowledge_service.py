"""
Knowledge Base Explorer service - the only thing the UI talks to for
KB search/browse/filter. Owns pagination math and mode selection
(search vs browse) so that logic lives in one place, not duplicated
in views.py.
"""

from dataclasses import dataclass

from src.repositories.fact_repository import ChunkFilter, FactRepository, KnowledgeChunk


@dataclass(frozen=True)
class ExplorerPage:
    chunks: list[KnowledgeChunk]
    total_count: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.total_count == 0:
            return 1
        return (self.total_count + self.page_size - 1) // self.page_size


class KnowledgeService:
    def __init__(self, fact_repository: FactRepository) -> None:
        self._fact_repository = fact_repository

    def filter_options(self) -> dict[str, list[str]]:
        return self._fact_repository.filter_options()

    def browse(
        self,
        sport: str | None = None,
        source: str | None = None,
        tag: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        search_text: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> ExplorerPage:
        """
        Browse mode: metadata-filtered listing, no query embedding involved.
        If search_text is set, this still does a plain substring match
        (see semantic_search for real embedding-similarity search).
        """
        filters = ChunkFilter(
            sport=sport, source=source, tag=tag, date_from=date_from, date_to=date_to, search_text=search_text
        )
        offset = (page - 1) * page_size
        chunks, total = self._fact_repository.browse(filters, offset=offset, limit=page_size)
        return ExplorerPage(chunks=chunks, total_count=total, page=page, page_size=page_size)

    def search(
        self,
        query_text: str,
        sport: str | None = None,
        source: str | None = None,
        tag: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> list[KnowledgeChunk]:
        """Search mode: real embedding similarity search against query_text."""
        filters = ChunkFilter(sport=sport, source=source, tag=tag, date_from=date_from, date_to=date_to)
        return self._fact_repository.semantic_search(query_text, filters, limit=limit)