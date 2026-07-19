"""
Generation-layer contracts — the schema-first backbone of the app.

GenerationRequest is the validated input boundary (Sport/Difficulty are
closed enums, not free text — this alone kills a class of prompt-injection
and typo bugs). Question/Quiz are the *only* shape the LLM is allowed to
hand back to the UI: raw LLM text never reaches Streamlit directly, it
always passes through JSON-mode + this schema first.
"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from src.schemas.retrieval import SourceType


class Sport(str, Enum):
    CRICKET = "Cricket"
    FOOTBALL = "Football"
    BADMINTON = "Badminton"
    TENNIS = "Tennis"
    BASKETBALL = "Basketball"


class Difficulty(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"


class GenerationRequest(BaseModel):
    """Validated input for a single quiz-generation use case."""

    sport: Sport
    difficulty: Difficulty
    question_count: int = Field(default=3, ge=1, le=10)


class SourceAttribution(BaseModel):
    """Tells the UI which retrieved item(s) grounded a given question."""

    source_type: SourceType
    label: str = Field(..., description="e.g. 'Local KB' or the web article title.")
    url: str | None = None
    excerpt: str = Field(..., description="The exact snippet used to ground this question.")


class Question(BaseModel):
    """A single validated, grounded multiple-choice question."""

    question: str = Field(..., min_length=1)
    options: dict[str, str] = Field(
        ..., description="Keys must be exactly {'A','B','C','D'}."
    )
    correct_answer: str = Field(..., min_length=1, max_length=1)
    explanation: str = Field(..., min_length=1)
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Derived from grounding-source relevance."
    )
    sources: list[SourceAttribution] = Field(default_factory=list)

    @field_validator("options")
    @classmethod
    def _exact_option_keys(cls, v: dict[str, str]) -> dict[str, str]:
        expected = {"A", "B", "C", "D"}
        if set(v.keys()) != expected:
            raise ValueError(f"options must have exactly keys {expected}, got {set(v.keys())}")
        return v

    @field_validator("correct_answer")
    @classmethod
    def _answer_is_valid_option(cls, v: str) -> str:
        upper = v.strip().upper()
        if upper not in {"A", "B", "C", "D"}:
            raise ValueError(f"correct_answer must be one of A/B/C/D, got {v!r}")
        return upper


class Quiz(BaseModel):
    """The full validated output of the generation pipeline."""

    sport: Sport
    difficulty: Difficulty
    questions: list[Question] = Field(..., min_length=1)
    prompt_version: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str
    generation_time_ms: float | None = Field(
        default=None,
        description=(
            "Wall-clock time for the fresh-generation pipeline in ms. "
            "None for cache hits or quizzes generated before this field existed - "
            "additive field, does not break existing JSON."
        ),
    )