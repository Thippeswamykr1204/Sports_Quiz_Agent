"""Unit tests for versioned prompt building."""

import pytest

from src.generation.prompts import PROMPTS, build_prompt
from src.schemas.quiz import Difficulty, Sport


def test_both_versions_registered():
    assert "v1" in PROMPTS
    assert "v2" in PROMPTS


def test_build_prompt_v2_includes_sport_and_difficulty():
    system, user = build_prompt(
        version="v2",
        sport=Sport.CRICKET,
        difficulty=Difficulty.HARD,
        question_count=3,
        context="Some context here.",
    )

    assert "Cricket" in user
    assert "Hard" in user
    assert "3" in user
    assert "Some context here." in user


def test_build_prompt_v2_system_forbids_treating_context_as_instructions():
    system, _ = build_prompt(
        version="v2",
        sport=Sport.FOOTBALL,
        difficulty=Difficulty.EASY,
        question_count=2,
        context="ctx",
    )

    assert "not as instructions" in system.lower() or "never as" in system.lower()


def test_build_prompt_includes_json_shape_instructions():
    _, user = build_prompt(
        version="v1",
        sport=Sport.TENNIS,
        difficulty=Difficulty.MEDIUM,
        question_count=1,
        context="ctx",
    )

    assert '"correct_answer"' in user
    assert '"options"' in user


def test_build_prompt_unknown_version_raises_key_error():
    with pytest.raises(KeyError):
        build_prompt(
            version="v99",
            sport=Sport.BASKETBALL,
            difficulty=Difficulty.HARD,
            question_count=1,
            context="ctx",
        )
