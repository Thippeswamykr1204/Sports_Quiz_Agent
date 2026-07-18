"""
Unit tests for quiz_generator.py.

LLMClient is a fake/stub here — these tests verify the parse-validate-
fallback orchestration logic, independent of any real LLM provider.
"""

import json

import pytest

from src.core.exceptions import SchemaValidationError
from src.core.request_context import request_scope
from src.generation.quiz_generator import generate_quiz
from src.schemas.quiz import Difficulty, GenerationRequest, Sport

_VALID_JSON_RESPONSE = json.dumps(
    {
        "questions": [
            {
                "question": "Who won the first FIFA World Cup?",
                "options": {"A": "Argentina", "B": "Uruguay", "C": "Brazil", "D": "Italy"},
                "correct_answer": "B",
                "explanation": "Uruguay won in 1930.",
                "confidence": 0.9,
            }
        ]
    }
)

_LEGACY_TEXT_RESPONSE = """
Question: Who won the first FIFA World Cup?
A) Argentina
B) Uruguay
C) Brazil
D) Italy
Correct Answer: B
Explanation: Uruguay won in 1930.
---
""".strip()


class _StubLLMClient:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        return self._response_text


@pytest.fixture
def request_obj():
    return GenerationRequest(sport=Sport.FOOTBALL, difficulty=Difficulty.MEDIUM, question_count=1)


def test_generate_quiz_success_with_valid_json(request_obj):
    client = _StubLLMClient(_VALID_JSON_RESPONSE)

    with request_scope() as rid:
        quiz = generate_quiz(
            request=request_obj,
            compressed_context="Uruguay won the 1930 World Cup.",
            prompt_version="v2",
            llm_client=client,
        )

    assert len(quiz.questions) == 1
    assert quiz.questions[0].correct_answer == "B"
    assert quiz.prompt_version == "v2"
    assert quiz.request_id == rid


def test_generate_quiz_falls_back_to_legacy_parser_on_bad_json(request_obj):
    client = _StubLLMClient(_LEGACY_TEXT_RESPONSE)

    with request_scope():
        quiz = generate_quiz(
            request=request_obj,
            compressed_context="Uruguay won the 1930 World Cup.",
            prompt_version="v2",
            llm_client=client,
        )

    assert len(quiz.questions) == 1
    assert quiz.questions[0].correct_answer == "B"


def test_generate_quiz_raises_schema_validation_error_on_total_garbage(request_obj):
    client = _StubLLMClient("This is not JSON and not legacy format either.")

    with request_scope():
        with pytest.raises(SchemaValidationError):
            generate_quiz(
                request=request_obj,
                compressed_context="some context",
                prompt_version="v2",
                llm_client=client,
            )


def test_generate_quiz_raises_on_malformed_question_schema(request_obj):
    bad_json = json.dumps(
        {
            "questions": [
                {
                    "question": "Bad question",
                    "options": {"A": "x", "B": "y"},  # missing C, D — invalid
                    "correct_answer": "A",
                    "explanation": "e",
                    "confidence": 0.5,
                }
            ]
        }
    )
    client = _StubLLMClient(bad_json)

    with request_scope():
        with pytest.raises(SchemaValidationError):
            generate_quiz(
                request=request_obj,
                compressed_context="ctx",
                prompt_version="v2",
                llm_client=client,
            )


def test_generate_quiz_works_with_empty_context(request_obj):
    client = _StubLLMClient(_VALID_JSON_RESPONSE)

    with request_scope():
        quiz = generate_quiz(
            request=request_obj,
            compressed_context="",
            prompt_version="v1",
            llm_client=client,
        )

    assert len(quiz.questions) == 1
