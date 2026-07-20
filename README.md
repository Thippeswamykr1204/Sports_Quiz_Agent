# Sports Quiz Agent

A retrieval-augmented sports quiz generator. Pick a sport and a difficulty,
and it builds multiple-choice questions grounded in a local knowledge base
and live web search — not invented from the LLM's memory alone. Every
question ships with a confidence score and the sources that grounded it.

Built on Streamlit, ChromaDB, and Gemini.

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Security](#security)
- [Observability](#observability)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)

## Features

- **Grounded generation** — every question is built from local knowledge-base
  facts and/or fresh web search results, never from the model's unaided
  recall
- **Source transparency** — each question shows a per-question confidence
  score and the exact facts/snippets that grounded it; an "AI Transparency
  Mode" trace view exposes every pipeline stage (retrieval, merge,
  compression, generation) with timing and token usage
- **In-app scoring** — answer inline, get immediate correctness feedback and
  an explanation, and have every attempt recorded for the Analytics page
  (average score, best performance, weakest category — computed from
  recorded attempts, not the model's confidence score)
- **Quiz history** — every generated quiz is persisted; browse, filter, and
  re-open past quizzes
- **Response caching** — identical sport/difficulty/day requests are served
  from cache instead of re-querying the LLM
- **Knowledge Base Explorer** — browse or semantically search the underlying
  fact store directly, independent of quiz generation
- **Export** — copy a quiz as Markdown or download it as JSON

## Quick start

Requires Python 3.11+ and a [Google AI Studio](https://aistudio.google.com/)
API key for Gemini.

```bash
python3.11 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# edit .env and set GOOGLE_API_KEY

streamlit run app.py
```

The app seeds its local knowledge base (`data/sports_facts.json`) into
ChromaDB on first run and applies SQLite migrations automatically — no
separate setup step needed.

## Configuration

All configuration is environment-driven (`src/config/settings.py`, backed by
`pydantic-settings`). See `.env.example` for the full list with defaults.
The app fails fast at startup — with a clear message — if `GOOGLE_API_KEY`
is missing, rather than failing deep inside a request.

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | *(required)* | Gemini API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Model used for generation |
| `LLM_TEMPERATURE` | `0.7` | Generation temperature |
| `LLM_MAX_RETRIES` | `2` | Retries on transient Gemini errors |
| `ACTIVE_PROMPT_VERSION` | `v2` | Selects the prompt template (see `src/generation/prompts.py`) |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Vector store location |
| `SPORTS_FACTS_PATH` | `./data/sports_facts.json` | Seed data for the knowledge base |
| `LOCAL_RETRIEVAL_TOP_K` / `WEB_RETRIEVAL_TOP_K` | `3` / `3` | Chunks pulled per source per request |
| `MAX_CONTEXT_TOKENS` | `1500` | Token budget for the compressed context passed to the LLM |
| `CACHE_DIR` / `CACHE_TTL_SECONDS` | `./.cache` / `21600` | Disk cache location and TTL |
| `LOG_LEVEL` | `INFO` | Structured log verbosity |
| `ENVIRONMENT` | `development` | Free-text env tag, included in every log line |

Some of these (theme, model, temperature, max questions, confidence
threshold, prompt version, cache TTL) can also be overridden at runtime from
the in-app **Settings** page — those overrides are persisted to SQLite and
take precedence over the `.env` value until cleared.

## Architecture

Four layers, each with one job:

```
Presentation   src/ui/          Streamlit views + components. No business logic.
Orchestration  src/services/    Use-case composition (QuizService, AnalyticsService, ...)
Retrieval/Gen  src/repositories/, src/generation/   ChromaDB, web search, prompt building, LLM calls
Foundation     src/core/, src/config/, src/schemas/  Logging, caching, migrations, settings, Pydantic schemas
```

`QuizService` (`src/services/quiz_service.py`) is the only class the UI talks
to for quiz generation. It never imports `chromadb`, `duckduckgo_search`, or
the Gemini SDK directly — those live behind repository and generation
abstractions it composes. A single request flows:

```
validate request
  -> build retrieval queries (query_builder.py)
  -> retrieve from local KB (ChromaDB) + live web (DuckDuckGo)
  -> merge + deduplicate (merge.py)
  -> compress to fit the token budget (context_compressor.py)
  -> build versioned prompt (prompts.py) -> call Gemini in JSON mode
  -> validate response against Pydantic schemas, fallback-parse once on failure
  -> cache, persist to history, return
```

Retrieval is partial-tolerant: if web search fails, the service logs a
warning and proceeds on local facts alone (and vice versa). Only a total
absence of context from both sources is treated as fatal.

Prompt-injection defense is layered: `sanitization.py` strips control
characters, code fences, and known injection phrases from retrieved web
snippets before they ever reach a prompt, and the prompt template itself
explicitly instructs the model to treat retrieved context as data, not
instructions. Neither is a silver bullet on its own — that's why both exist.

## Project structure

```
app.py                          Streamlit entrypoint — wiring only
src/
  config/settings.py            Env-driven config, fails fast on invalid/missing values
  core/
    cache.py                    Disk-backed response cache (diskcache)
    db.py                       Shared SQLite connection helper (commit/rollback + guaranteed close)
    exceptions.py               Domain exception hierarchy
    logging.py                  structlog config, request-scoped log context
    metrics.py                  In-process counters (cache hit rate, avg latency, ...)
    migrations.py               Versioned, idempotent SQLite schema migrations
    rate_limiter.py             Sliding-window rate limiter (opt-in, not wired by default)
    request_context.py          ContextVar-based request_id propagation
    tracing.py                  AI Transparency Mode: per-request pipeline trace capture
  generation/
    context_compressor.py       Token-budget-aware context compression
    fallback_parser.py          Regex-based recovery parser for non-JSON LLM output
    gemini_client.py            Gemini SDK wrapper: JSON mode, retries, structured errors
    llm_client.py                LLM client Protocol + an OpenAI-compatible implementation
    prompts.py                   Versioned prompt templates
    quiz_generator.py            Prompt -> LLM call -> schema validation -> Quiz
  repositories/
    attempt_repository.py        Per-question answer outcomes (SQLite)
    fact_repository.py           Local knowledge base access (ChromaDB)
    history_repository.py        Quiz generation history (SQLite)
    sanitization.py              Prompt-injection defenses for retrieved web text
    settings_repository.py       Persisted user settings overrides (SQLite)
    web_repository.py            Live web search (DuckDuckGo)
  schemas/                        Pydantic models: Quiz, Question, retrieval types, seed data
  services/
    analytics_service.py         Derives Analytics-page metrics from history + attempts
    history_service.py           Quiz history use cases
    knowledge_service.py         Knowledge Base Explorer use cases
    merge.py                      Merge + dedupe local/web retrieval results
    query_builder.py             Builds retrieval queries from a generation request
    quiz_service.py               Orchestration layer — the one class the UI depends on
    settings_service.py           Typed read/write over persisted settings, with env fallback
  ui/
    components.py                Reusable render_* functions
    state.py                      Centralized st.session_state access
    theme.py                      CSS
    views.py                      One section per app page
tests/
  unit/                          One test module per src module, external calls mocked
  integration/                    Full QuizService pipeline, still without real network calls
```

## Testing

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -v
```

75 tests (unit + integration), zero external network calls — every
ChromaDB/web-search/Gemini boundary is mocked or faked, so the suite runs
offline and deterministically.

## Security

- **Input validation** — every LLM response and repository row is validated
  against a Pydantic schema before it's trusted; malformed data raises
  rather than silently coercing.
- **Prompt-injection defenses** — see [Architecture](#architecture) above.
- **XSS** — any text that could originate from a web search result, the
  LLM, or the knowledge base is HTML-escaped before it's interpolated into
  a Streamlit `unsafe_allow_html` block. Search-result URLs are restricted
  to `http`/`https` schemes before they're ever rendered as a clickable
  link.
- **SQL** — every query is parameterized; `LIKE` search input has `%`/`_`
  escaped so user input can't widen a search pattern.
- **Secrets** — `GOOGLE_API_KEY` is read from the environment only, never
  logged, and the app refuses to start without a syntactically valid key.
- **Resource handling** — every SQLite connection is opened and closed
  through a single helper (`src/core/db.py`) that guarantees `close()` runs
  even on error; nothing relies on garbage collection to release a file
  handle.
- **Rate limiting** — `InMemoryRateLimiter` (`src/core/rate_limiter.py`) is
  available and thread-safe, but not wired into `QuizService` by default;
  wire it in `app.py`'s `build_service()` before exposing this to
  multiple untrusted users.

## Observability

- **Structured logs** (`structlog`) — every log line carries a `request_id`
  propagated through retrieval, generation, and persistence via a
  `ContextVar`, so a single request's full trace can be grepped out of the
  log file even under concurrent traffic.
- **Metrics** (`src/core/metrics.py`) — cache hit rate, average generation
  latency, and total quizzes served, in-process.
- **AI Transparency Mode** (`src/core/tracing.py`) — per-request pipeline
  trace: each stage's status and duration, retrieved items with their
  relevance scores, token usage when the provider reports it, retry count.
  Viewable per-quiz in the UI.
- **Health check** — `QuizService.health_check()` backs the Home page's
  status cards. A component is only ever reported `ok`/`degraded` if it was
  actually probed; components that aren't cheap to probe live (a Gemini
  completion call, for instance) are reported `unknown` with an explanation
  rather than a green light the app can't back up.

Both metrics and traces are in-process and reset on restart — see
[Known limitations](#known-limitations).

## Known limitations

Being upfront about these rather than papering over them:

- **Single-process metrics/traces.** `ServiceMetrics` and the trace store
  are in-memory, per-process. They're accurate for the server they run on,
  but reset on restart and don't aggregate across a multi-worker deployment.
  Fine for the current single-process Streamlit deployment; a horizontally
  scaled deployment needs these pushed to a shared store (Redis,
  Prometheus) instead.
- **Rate limiting is opt-in.** Built and tested, but not wired into
  `QuizService` by default — see [Security](#security).
- **"Today's statistics" is process-lifetime, not calendar-day.** There's no
  persistence layer yet distinguishing calendar days from "since this
  server process started"; the UI caption says so explicitly.
- **Per-question source attribution is coarse.** All questions in a quiz
  are attributed the same top-N retrieved items, since the LLM's JSON
  output doesn't currently return per-question citation indices.
- **Single LLM provider wired in.** `LLMClient` is a `Protocol`, and an
  OpenAI-compatible implementation already exists
  (`src/generation/llm_client.py`), but only `GeminiLLMClient` is wired
  into `app.py` today.

## Roadmap

- Wire `InMemoryRateLimiter` into `QuizService` (or swap in a
  Redis-backed implementation) before any multi-user deployment
- Push metrics/traces to a shared store for multi-worker deployments
- Per-question citation indices from the LLM, for precise (not
  quiz-level) source attribution
- Second LLM provider behind the existing `LLMClient` Protocol