"""
Context compression.

Takes the Merge + Deduplicate output (MergedContext) and produces a single
prompt-ready text block, trimmed to a token budget so retrieval growth
over time can't silently blow out the prompt. Items are kept in
descending relevance order, so if the budget is tight we keep the best
evidence, not just whatever was merged first.

Token counting here is a documented approximation (~4 characters per
token, a widely used rule of thumb for English text) rather than a real
tokenizer — swappable behind `estimate_tokens` if a real tokenizer becomes
available in the deployment environment.

PROMPT INJECTION NOTE: WebSnippet text comes from live web search results
— content an attacker can influence by publishing a page the search
ranks highly (e.g. "IGNORE ALL PREVIOUS INSTRUCTIONS AND..."). The v2
prompt template (prompts.py) already fences CONTEXT with explicit
"treat as data, not instructions" framing, which is the primary
defense. _sanitize_web_text below is defense-in-depth on top of that:
it neutralizes the most common raw injection patterns (fake role
markers, nested code fences that could be used to spoof a new
instruction block) before the text is even placed inside the CONTEXT
block. RetrievedFact text is NOT sanitized here — it comes from the
deployer's own static seed file, not from an untrusted network source.
"""

import re

from src.schemas.retrieval import MergedContext, RetrievedFact, WebSnippet

_CHARS_PER_TOKEN_ESTIMATE = 4
_MAX_WEB_SNIPPET_CHARS = 800

# Case-insensitive line-start role markers a hostile page might use to
# impersonate a system/assistant turn and try to hijack the model.
_ROLE_MARKER_PATTERN = re.compile(
    r"^\s*(system|assistant|user)\s*:", re.IGNORECASE | re.MULTILINE
)
_CODE_FENCE_PATTERN = re.compile(r"```")


def estimate_tokens(text: str) -> int:
    """Approximate token count for budget purposes. Not exact — see module docstring."""
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


def _sanitize_web_text(text: str) -> str:
    """Neutralizes common prompt-injection patterns in untrusted web content. See module docstring."""
    text = _ROLE_MARKER_PATTERN.sub(lambda m: f"[{m.group(1)} (quoted from source)]:", text)
    text = _CODE_FENCE_PATTERN.sub("'''", text)
    if len(text) > _MAX_WEB_SNIPPET_CHARS:
        text = text[:_MAX_WEB_SNIPPET_CHARS].rstrip() + "…"
    return text


def _item_label(item: RetrievedFact | WebSnippet) -> str:
    if isinstance(item, RetrievedFact):
        return "[Local KB]"
    return f"[Web: {item.title}]"


def _item_text(item: RetrievedFact | WebSnippet) -> str:
    if isinstance(item, WebSnippet):
        return _sanitize_web_text(item.text)
    return item.text


def compress_context(merged: MergedContext, max_tokens: int) -> str:
    """
    Builds the final context string handed to the prompt builder.

    Greedy strategy: sort by relevance_score descending, add items one at
    a time until adding the next would exceed max_tokens. Returns an empty
    string (not an error) if merged has no items — the caller
    (quiz_generator) decides whether an empty context is fatal.
    """
    if merged.is_empty:
        return ""

    ordered = sorted(merged.items, key=lambda i: i.relevance_score, reverse=True)

    included_lines: list[str] = []
    used_tokens = 0

    for item in ordered:
        line = f"{_item_label(item)} {_item_text(item)}"
        line_tokens = estimate_tokens(line)

        if used_tokens + line_tokens > max_tokens and included_lines:
            # Budget exhausted, but we already have at least one item — stop here.
            break

        included_lines.append(line)
        used_tokens += line_tokens

        if used_tokens >= max_tokens:
            break

    return "\n".join(included_lines)