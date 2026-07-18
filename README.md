# Sports Quiz Agent

An AI-powered sports quiz generator, built as a RAG (Retrieval-Augmented
Generation) application: every question is grounded in a local knowledge
base and live web search, never invented from the LLM's memory alone.

Built as a production-grade redesign of a beginner-level Streamlit +
ChromaDB assignment - see `docs/ARCHITECTURE.md` for the full design
rationale and `docs/SECURITY.md` for the security posture.

## Features

- Pick a sport and difficulty, get grounded multiple-choice questions
- Every answer is checkable in-app with an explanation
- Source-transparent: each quiz shows which local facts and web snippets
  grounded it, with a confidence indicator per question
- Copy quiz as Markdown or export as JSON
- Recent-quiz history in the sidebar
- Response caching (same sport+difficulty+day = instant repeat)

## Quick start

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then set OPENAI_API_KEY
streamlit run app.py
```

Full setup, Docker, and platform-specific deployment instructions:
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**

## Architecture

Layered: Presentation (Streamlit) -> Orchestration (Service Layer) ->
Retrieval (ChromaDB + DuckDuckGo, Repository Pattern) + Generation
(versioned prompts, JSON-mode LLM calls, schema validation).

Full breakdown, design patterns, and documented simplifications:
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

## Security

Output/input validation, prompt-injection defenses, secret handling,
rate-limit hook, audit logging, and real dependency-scan findings with
mitigations: **[docs/SECURITY.md](docs/SECURITY.md)**

## Running tests

```bash
pip install -r requirements.txt
OPENAI_API_KEY=sk-test PYTHONPATH=. python -m pytest tests/ -v
```

75 tests (unit + integration), zero external network calls - all
retrieval/LLM boundaries are mocked or faked in tests.

## Project structure

```
src/
├── config/        # Fail-fast settings
├── schemas/       # Pydantic contracts (Sport, Difficulty, Quiz, Question, ...)
├── repositories/  # ChromaDB + DuckDuckGo retrieval, snippet sanitization
├── generation/    # Prompts, context compression, LLM client, output validation
├── services/      # QuizService - the orchestration pipeline
├── core/          # Exceptions, logging, request context, cache, rate limiter
└── ui/            # Streamlit views, components, state, theme
tests/
├── unit/          # One module at a time, mocked dependencies
└── integration/   # Full pipeline, faked external services
data/sports_facts.json   # Seed knowledge base
app.py                    # Entrypoint
```

See `docs/ARCHITECTURE.md` for what belongs in each folder and why.

## Known limitations

- Source attribution is per-quiz, not per-question (see Architecture doc)
- Token budgeting uses an approximation, not a real tokenizer
- Rate limiting is in-process only (fine for single-instance deployments)
- First run needs network access to download the embedding model - see
  Deployment doc's Troubleshooting section if this fails

## Development milestones

This project was built incrementally, milestone by milestone, with tests
passing at every stage:

1. Foundation (config, schemas, exceptions, logging, request context)
2. Local retrieval (ChromaDB repository)
3. Web retrieval (DuckDuckGo repository + prompt-injection sanitization)
4. Generation layer (versioned prompts, context compression, LLM client, schema validation)
5. Orchestration + caching (the full pipeline, merge/dedupe, disk cache)
6. UI (Streamlit views, source chips, confidence indicators, export actions)
7. Hardening (rate limiting, audit logging, dependency scanning)
8. Packaging (Docker, docs) - this milestone
