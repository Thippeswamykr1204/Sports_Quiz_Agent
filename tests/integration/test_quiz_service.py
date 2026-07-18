"""
Integration tests for QuizService.

These exercise the *whole pipeline* (validate -> retrieve -> merge ->
compress -> generate -> cache) end-to-end, but with fake implementations
of FactRepository, WebRepository, LLMClient, and QuizCache — no real
network, ChromaDB, or OpenAI calls. This is the integration layer: it
verifies the pieces built in M1-M5 actually compose correctly.
"""

import json

import pytest

from src.core.exceptions import NoContextAvailableError, RateLimitExceededError, RetrievalError
from src.schemas.quiz import Difficulty, GenerationRequest, Sport
from src.schemas.retrieval import RetrievedFact, WebSnippet
from src.services.quiz_service import QuizService

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


class _FakeFactRepository:
    def __init__(self, facts=None, raise_error=False):
        self._facts = facts if facts is not None else [
            RetrievedFact(text="Uruguay won the first World Cup in 1930.", sport="Football", relevance_score=0.9)
        ]
        self._raise_error = raise_error

    def query(self, sport, query_text, top_k):
        if self._raise_error:
            raise RetrievalError("local_kb", "simulated failure")
        return self._facts


class _FakeWebRepository:
    def __init__(self, snippets=None, raise_error=False):
        self._snippets = snippets if snippets is not None else [
            WebSnippet(title="News", text="Recent football tournament news snippet.", url="https://x.com", relevance_score=0.7)
        ]
        self._raise_error = raise_error

    def search(self, sport, query_text, top_k):
        if self._raise_error:
            raise RetrievalError("web", "simulated failure")
        return self._snippets


class _FakeLLMClient:
    def __init__(self, response_text=_VALID_JSON_RESPONSE):
        self._response_text = response_text
        self.call_count = 0

    def generate_json(self, system_prompt, user_prompt):
        self.call_count += 1
        return self._response_text


class _FakeCache:
    def __init__(self):
        self._store = {}

    def get(self, sport, difficulty, prompt_version):
        return self._store.get((sport, difficulty, prompt_version))

    def set(self, sport, difficulty, prompt_version, quiz, ttl_seconds):
        self._store[(sport, difficulty, prompt_version)] = quiz


@pytest.fixture
def request_obj():
    return GenerationRequest(sport=Sport.FOOTBALL, difficulty=Difficulty.MEDIUM, question_count=1)


def _make_service(**overrides):
    defaults = dict(
        fact_repository=_FakeFactRepository(),
        web_repository=_FakeWebRepository(),
        llm_client=_FakeLLMClient(),
        cache=None,
    )
    defaults.update(overrides)
    return QuizService(**defaults)


def test_full_pipeline_produces_valid_quiz(request_obj):
    service = _make_service()

    quiz = service.generate(request_obj)

    assert len(quiz.questions) == 1
    assert quiz.sport == Sport.FOOTBALL
    assert quiz.request_id  # populated by request_scope


def test_pipeline_continues_when_web_retrieval_fails(request_obj):
    service = _make_service(web_repository=_FakeWebRepository(raise_error=True))

    quiz = service.generate(request_obj)

    assert len(quiz.questions) == 1  # local facts alone were enough


def test_pipeline_continues_when_local_retrieval_fails(request_obj):
    service = _make_service(fact_repository=_FakeFactRepository(raise_error=True))

    quiz = service.generate(request_obj)

    assert len(quiz.questions) == 1  # web snippets alone were enough


def test_pipeline_raises_when_both_sources_fail(request_obj):
    service = _make_service(
        fact_repository=_FakeFactRepository(raise_error=True),
        web_repository=_FakeWebRepository(raise_error=True),
    )

    with pytest.raises(NoContextAvailableError):
        service.generate(request_obj)


def test_pipeline_uses_cache_on_second_call(request_obj):
    llm_client = _FakeLLMClient()
    service = _make_service(llm_client=llm_client, cache=_FakeCache())

    first = service.generate(request_obj)
    second = service.generate(request_obj)

    assert llm_client.call_count == 1  # second call served from cache, no new LLM call
    assert first.questions[0].question == second.questions[0].question


def test_pipeline_generates_distinct_request_ids_per_call(request_obj):
    service = _make_service()

    first = service.generate(request_obj)
    second = service.generate(request_obj)

    assert first.request_id != second.request_id


def test_pipeline_attaches_source_attribution_to_questions(request_obj):
    service = _make_service()

    quiz = service.generate(request_obj)

    assert len(quiz.questions[0].sources) > 0
    assert all(s.excerpt for s in quiz.questions[0].sources)


class _AlwaysDenyRateLimiter:
    def check(self, identity):
        from src.core.exceptions import RateLimitExceededError

        raise RateLimitExceededError(identity, retry_after_seconds=5.0)


class _AlwaysAllowRateLimiter:
    def check(self, identity):
        pass


def test_pipeline_raises_when_rate_limiter_denies(request_obj):
    service = _make_service(rate_limiter=_AlwaysDenyRateLimiter())

    with pytest.raises(RateLimitExceededError):
        service.generate(request_obj)


def test_pipeline_proceeds_when_rate_limiter_allows(request_obj):
    service = _make_service(rate_limiter=_AlwaysAllowRateLimiter())

    quiz = service.generate(request_obj)

    assert len(quiz.questions) == 1


def test_pipeline_emits_audit_log_on_success(request_obj, capsys):
    service = _make_service()

    service.generate(request_obj)

    captured = capsys.readouterr()
    assert "audit_event" in captured.out
    assert "outcome=success" in captured.out


def test_pipeline_emits_audit_log_on_rate_limit(request_obj, capsys):
    service = _make_service(rate_limiter=_AlwaysDenyRateLimiter())

    with pytest.raises(RateLimitExceededError):
        service.generate(request_obj)

    captured = capsys.readouterr()
    assert "audit_event" in captured.out
    assert "outcome=rate_limited" in captured.out
