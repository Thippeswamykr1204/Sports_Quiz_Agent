"""Unit tests for the legacy text-format fallback parser."""

from src.generation.fallback_parser import parse_legacy_text_format

_SAMPLE_TEXT = """
Question: Who won the first FIFA World Cup?
A) Argentina
B) Uruguay
C) Brazil
D) Italy
Correct Answer: B
Explanation: Uruguay hosted and won the first World Cup in 1930.
---
Question: What year was the first cricket Test match played?
A) 1877
B) 1900
C) 1930
D) 1948
Correct Answer: A
Explanation: The first Test match was played in 1877 at the MCG.
---
""".strip()


def test_parse_legacy_format_extracts_all_questions():
    result = parse_legacy_text_format(_SAMPLE_TEXT)

    assert len(result) == 2


def test_parse_legacy_format_extracts_correct_fields():
    result = parse_legacy_text_format(_SAMPLE_TEXT)
    first = result[0]

    assert first["question"] == "Who won the first FIFA World Cup?"
    assert first["options"]["B"] == "Uruguay"
    assert first["correct_answer"] == "B"
    assert "Uruguay hosted" in first["explanation"]


def test_parse_legacy_format_assigns_default_confidence():
    result = parse_legacy_text_format(_SAMPLE_TEXT)

    assert all(q["confidence"] == 0.5 for q in result)


def test_parse_legacy_format_returns_empty_list_for_unmatchable_text():
    result = parse_legacy_text_format("This is just random prose, no structure at all.")

    assert result == []
