"""
Unit tests for OpenAILLMClient.

The OpenAI SDK client is mocked — these tests verify our retry/backoff
and error-translation wrapping, not OpenAI's live API.
"""

import pytest
from openai import APIConnectionError, RateLimitError

from src.core.exceptions import GenerationError
from src.generation.llm_client import OpenAILLMClient


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


@pytest.fixture
def client():
    return OpenAILLMClient(
        api_key="sk-test",
        model="gpt-4o-mini",
        max_retries=1,
        backoff_seconds=0.01,
    )


def test_generate_json_returns_content_on_success(client, monkeypatch):
    monkeypatch.setattr(
        client._client.chat.completions,
        "create",
        lambda **kwargs: _FakeResponse('{"questions": []}'),
    )

    result = client.generate_json("system", "user")

    assert result == '{"questions": []}'


def test_generate_json_raises_generation_error_on_empty_content(client, monkeypatch):
    monkeypatch.setattr(
        client._client.chat.completions,
        "create",
        lambda **kwargs: _FakeResponse(None),
    )

    with pytest.raises(GenerationError, match="empty response"):
        client.generate_json("system", "user")


def test_generate_json_retries_on_transient_error_then_succeeds(client, monkeypatch):
    call_count = {"n": 0}

    def flaky_create(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise APIConnectionError(request=None)
        return _FakeResponse('{"questions": []}')

    monkeypatch.setattr(client._client.chat.completions, "create", flaky_create)

    result = client.generate_json("system", "user")

    assert call_count["n"] == 2
    assert result == '{"questions": []}'


def test_generate_json_raises_after_exhausting_retries(client, monkeypatch):
    def always_fails(**kwargs):
        raise APIConnectionError(request=None)

    monkeypatch.setattr(client._client.chat.completions, "create", always_fails)

    with pytest.raises(GenerationError, match="failed after"):
        client.generate_json("system", "user")
