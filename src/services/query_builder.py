"""
Query Builder step of the retrieval pipeline.

Separated out so the query strings sent to each retriever are visible,
testable, and tunable independently of the orchestration logic in
quiz_service.py.
"""

from src.schemas.quiz import Difficulty, Sport

_DIFFICULTY_HINTS = {
    Difficulty.EASY: "well-known facts basics",
    Difficulty.MEDIUM: "notable records achievements",
    Difficulty.HARD: "detailed history obscure records",
}


def build_local_query(sport: Sport, difficulty: Difficulty) -> str:
    """Query string sent to the local ChromaDB retriever."""
    return f"{sport.value} history championships rules records {_DIFFICULTY_HINTS[difficulty]}"


def build_web_query(sport: Sport) -> str:
    """Query string sent to the live web retriever — recency-focused, difficulty-agnostic."""
    return f"{sport.value} latest tournament results championship winners news"
