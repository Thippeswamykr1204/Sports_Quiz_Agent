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
"""

from src.schemas.retrieval import MergedContext, RetrievedFact, WebSnippet

_CHARS_PER_TOKEN_ESTIMATE = 4


def estimate_tokens(text: str) -> int:
    """Approximate token count for budget purposes. Not exact — see module docstring."""
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


def _item_label(item: RetrievedFact | WebSnippet) -> str:
    if isinstance(item, RetrievedFact):
        return "[Local KB]"
    return f"[Web: {item.title}]"


def _item_text(item: RetrievedFact | WebSnippet) -> str:
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
