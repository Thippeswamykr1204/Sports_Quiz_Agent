"""
Fallback parser for legacy-style text output.

JSON mode (llm_client.py) should make this unnecessary in normal
operation, but a model can still occasionally wrap JSON in prose despite
instructions, or a provider swap (Future Enhancement: multi-provider LLM
support) might not support JSON mode. This parser recovers the older
"Question: ... A) ... Correct Answer: X" format referenced in the
original assignment, so a single bad response degrades gracefully instead
of crashing the whole request.

This is a last resort: quiz_generator.py only calls this after
JSON parsing has already failed.
"""

import re

_QUESTION_BLOCK_PATTERN = re.compile(
    r"Question:\s*(?P<question>.+?)\s*"
    r"A\)\s*(?P<a>.+?)\s*"
    r"B\)\s*(?P<b>.+?)\s*"
    r"C\)\s*(?P<c>.+?)\s*"
    r"D\)\s*(?P<d>.+?)\s*"
    r"Correct Answer:\s*(?P<answer>[A-D])\s*"
    r"Explanation:\s*(?P<explanation>.+?)(?=(?:---)|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def parse_legacy_text_format(raw_text: str) -> list[dict]:
    """
    Extracts question dicts from the legacy pipe-delimited text format.

    Returns a list of dicts shaped like the JSON schema expects
    (question/options/correct_answer/explanation/confidence), so the
    caller can feed them straight into Pydantic validation. Returns an
    empty list if nothing matches — caller treats that as total failure.
    """
    questions = []
    for match in _QUESTION_BLOCK_PATTERN.finditer(raw_text):
        questions.append(
            {
                "question": match.group("question").strip(),
                "options": {
                    "A": match.group("a").strip(),
                    "B": match.group("b").strip(),
                    "C": match.group("c").strip(),
                    "D": match.group("d").strip(),
                },
                "correct_answer": match.group("answer").strip().upper(),
                "explanation": match.group("explanation").strip(),
                # No confidence signal in this legacy format — default to a
                # conservative mid-point rather than claiming false certainty.
                "confidence": 0.5,
            }
        )
    return questions
