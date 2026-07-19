"""
Schema for the raw local knowledge-base seed file (data/sports_facts.json).

Validating this at load time means a malformed seed file fails fast with a
clear DataLoadError instead of silently inserting garbage into ChromaDB
that surfaces as a confusing bug three layers away.
"""

from pydantic import BaseModel, Field


class SeedFact(BaseModel):
    """One entry in data/sports_facts.json before it becomes a RetrievedFact."""

    sport: str = Field(..., min_length=1)
    fact: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    date: str | None = Field(default=None, description="ISO date string if the fact is dated, else None.")
    source: str | None = Field(
        default=None,
        description="Where this fact came from. Defaults to 'Local Knowledge Base' at seed time if omitted.",
    )