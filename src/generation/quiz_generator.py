"""
Quiz generation orchestration (generation layer, not the service layer).

This is the only module allowed to touch raw LLM output. It:
1. Builds the versioned prompt from compressed context.
2. Calls the LLM client (JSON mode).
3. Validates the response against Question/Quiz schemas.
4. On JSON/schema failure, tries the legacy fallback text parser once.
5. On total failure, raises SchemaValidationError — the service layer
   (M5) decides what the user sees; this layer never fabricates a Quiz.

quiz_service.py (M5) is responsible for retrieval, merging, and context
compression before calling generate_quiz — this module assumes it already
has a compressed context string ready to prompt with.
"""

import json
import re
from contextlib import nullcontext

from pydantic import ValidationError

from src.core.exceptions import SchemaValidationError
from src.core.logging import get_logger
from src.core.request_context import get_request_id
from src.core.tracing import TraceBuilder
from src.generation.fallback_parser import parse_legacy_text_format
from src.generation.llm_client import LLMClient
from src.generation.prompts import build_prompt
from src.schemas.quiz import GenerationRequest, Question, Quiz

logger = get_logger("quiz_generator")

# Models occasionally wrap JSON-mode output in a markdown code fence
# despite instructions not to (```json ... ``` or plain ```...```).
# Stripping this before json.loads recovers an otherwise-perfectly-valid
# response instead of discarding it to the legacy text-format fallback,
# which expects a completely different shape and would also fail.
_MARKDOWN_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def _strip_markdown_fence(raw_output: str) -> str:
    match = _MARKDOWN_FENCE_PATTERN.match(raw_output.strip())
    return match.group(1) if match else raw_output


def _parse_and_validate_questions(raw_output: str) -> list[Question]:
    """
    Attempts JSON parsing + schema validation first, falls back to the
    legacy text parser once if that fails. Raises SchemaValidationError
    only if both paths fail.
    """
    try:
        payload = json.loads(_strip_markdown_fence(raw_output))
        raw_questions = payload["questions"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("json_parse_failed_trying_fallback", error=str(exc))
        raw_questions = parse_legacy_text_format(raw_output)
        if not raw_questions:
            raise SchemaValidationError(
                raw_output, f"could not parse JSON or legacy format: {exc}"
            ) from exc

    try:
        return [Question.model_validate(q) for q in raw_questions]
    except ValidationError as exc:
        raise SchemaValidationError(raw_output, f"question schema validation failed: {exc}") from exc


def generate_quiz(
    request: GenerationRequest,
    compressed_context: str,
    prompt_version: str,
    llm_client: LLMClient,
    trace_builder: TraceBuilder | None = None,
) -> Quiz:
    """
    Produces a fully validated Quiz for the given request and context.

    trace_builder is optional (AI Transparency Mode) - when provided,
    records real per-stage timing/status for Prompt Generation, Gemini
    Response, JSON Parsing, and Validation. When None, behaves exactly
    as before - existing callers/tests are unaffected.

    Raises:
        GenerationError: the LLM call itself failed (network, auth, etc.)
        SchemaValidationError: the LLM's output could not be validated
            even after the fallback parser.
    """
    if not compressed_context.strip():
        logger.warning(
            "generating_with_empty_context",
            sport=request.sport.value,
            difficulty=request.difficulty.value,
        )

    with trace_builder.stage("Prompt Generation") if trace_builder else nullcontext():
        system_prompt, user_prompt = build_prompt(
            version=prompt_version,
            sport=request.sport,
            difficulty=request.difficulty,
            question_count=request.question_count,
            context=compressed_context or "No context available.",
        )

    with trace_builder.stage("Gemini Response") if trace_builder else nullcontext():
        raw_output = llm_client.generate_json(system_prompt, user_prompt)

    if trace_builder is not None:
        get_metadata = getattr(llm_client, "get_last_call_metadata", None)
        if callable(get_metadata):
            call_meta = get_metadata()
            trace_builder.trace.retry_count = call_meta.get("retry_count", 0)
            trace_builder.trace.token_usage = call_meta.get("token_usage")

    with trace_builder.stage("JSON Parsing") if trace_builder else nullcontext():
        questions = _parse_and_validate_questions(raw_output)

    if not questions:
        raise SchemaValidationError(raw_output, "LLM returned zero valid questions.")

    with trace_builder.stage("Validation", detail=f"{len(questions)} questions validated") if trace_builder else nullcontext():
        quiz = Quiz(
            sport=request.sport,
            difficulty=request.difficulty,
            questions=questions,
            prompt_version=prompt_version,
            request_id=get_request_id(),
        )

    logger.info(
        "quiz_generated",
        sport=request.sport.value,
        difficulty=request.difficulty.value,
        question_count=len(questions),
        prompt_version=prompt_version,
    )
    return quiz