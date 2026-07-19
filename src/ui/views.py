"""
Top-level view composition.

render_sidebar() and render_router() are the only two functions app.py
calls. Everything here is composition: pulling state (ui/state.py),
rendering components (ui/components.py), and calling the service layer
(services/quiz_service.py) - no direct chromadb/openai/duckduckgo access.

Navigation model: a single active_section in session state (see
ui/state.py) drives which section function renders. This is Streamlit's
standard single-page pattern - no client routing, no URL, but a real
persistent nav rather than tabs re-rendered from scratch each time.
"""

import json
from collections import Counter

import streamlit as st

from src.config.settings import get_settings
from src.core.exceptions import GenerationError, NoContextAvailableError, SchemaValidationError
from src.schemas.quiz import Difficulty, GenerationRequest, Quiz, Sport
from src.services.quiz_service import QuizService
from src.ui import state
from src.ui.components import (
    render_empty_state,
    render_error_state,
    render_export_actions,
    render_loading_skeleton,
    render_question_card,
    render_quiz_header,
    render_stat_row,
)


# ---------------------------------------------------------------------------
# Sidebar: identity + navigation + generation controls
# ---------------------------------------------------------------------------

def render_sidebar() -> tuple[Sport, Difficulty, int, bool]:
    """Renders sidebar nav + quiz controls. Returns the current generation selections."""
    st.sidebar.markdown(
        '<div class="quiz-eyebrow">Sports Quiz Agent</div>',
        unsafe_allow_html=True,
    )

    active = state.get_active_section()
    for label, icon in state.NAV_SECTIONS:
        is_active = label == active
        if st.sidebar.button(
            f"{icon}  {label}",
            key=f"nav_{label}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
        ):
            state.set_active_section(label)
            st.rerun()

    st.sidebar.divider()
    st.sidebar.markdown('<div class="quiz-eyebrow">Quiz Settings</div>', unsafe_allow_html=True)

    sport = st.sidebar.selectbox("Sport", options=list(Sport), format_func=lambda s: s.value)
    difficulty = st.sidebar.select_slider(
        "Difficulty", options=list(Difficulty), format_func=lambda d: d.value
    )
    question_count = st.sidebar.slider("Number of questions", min_value=1, max_value=6, value=3)

    generate_clicked = st.sidebar.button(
        "Generate Fresh Quiz", use_container_width=True, type="primary"
    )
    if generate_clicked:
        state.set_active_section("Generate Quiz")

    return sport, difficulty, question_count, generate_clicked


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def render_router(service: QuizService, sport: Sport, difficulty: Difficulty, question_count: int) -> None:
    """Renders whichever section is active. Replaces the old single render_main call."""
    section = state.get_active_section()

    if section == "Home":
        _render_home(service)
    elif section == "Generate Quiz":
        _render_generate(sport, difficulty, question_count)
    elif section == "Quiz History":
        _render_history()
    elif section == "Analytics":
        _render_analytics()
    elif section == "Knowledge Base":
        _render_knowledge_base()
    elif section == "Settings":
        _render_settings()
    elif section == "About":
        _render_about()
    else:
        _render_home(service)


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

def _render_home(service: QuizService) -> None:
    st.markdown('<div class="quiz-gradient-bg" style="padding: 1.6rem 1.6rem 0.2rem; border-radius: 16px;">', unsafe_allow_html=True)
    st.markdown('<div class="quiz-eyebrow">Retrieval-grounded quiz generation</div>', unsafe_allow_html=True)
    st.title("Sports Quiz Agent")
    st.caption(
        "Grounded in a local knowledge base and live web search — every question "
        "is traceable to its source, never invented."
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.write("")

    _render_todays_statistics(service)
    st.write("")

    col_left, col_right = st.columns([3, 2])
    with col_left:
        _render_recent_activity()
    with col_right:
        _render_quick_actions()

    st.write("")
    _render_health_status(service)


def _render_todays_statistics(service: QuizService) -> None:
    """
    All-real numbers. "Today's" is honestly process-lifetime (see
    src/core/metrics.py) since there's no persistence layer distinguishing
    calendar days yet — flagged there as a Future Enhancement rather than
    faked here with a made-up "today" filter.
    """
    st.markdown('<div class="quiz-eyebrow">Today\'s statistics</div>', unsafe_allow_html=True)

    metrics = service.get_metrics()
    history = state.get_history()
    all_questions = [q for quiz in history for q in quiz.questions]

    avg_conf = (
        f"{round(100 * sum(q.confidence for q in all_questions) / len(all_questions))}%"
        if all_questions
        else "—"
    )
    avg_gen = (
        f"{metrics.avg_generation_ms / 1000:.1f}s" if metrics.avg_generation_ms is not None else "—"
    )
    hit_rate = (
        f"{round(metrics.cache_hit_rate * 100)}%" if metrics.cache_hit_rate is not None else "—"
    )
    kb_size = service.get_kb_size()

    render_stat_row(
        [
            ("Total quizzes", str(metrics.total_quizzes_served)),
            ("Avg. generation time", avg_gen),
            ("Avg. confidence", avg_conf),
            ("Cache hit rate", hit_rate),
            ("Knowledge base size", str(kb_size) if kb_size is not None else "unavailable"),
        ]
    )
    st.caption(
        "Counters are per-server-process since app start, not calendar-day scoped yet "
        "(see Future Enhancement note in src/core/metrics.py)."
    )


def _render_recent_activity() -> None:
    st.markdown('<div class="quiz-eyebrow">Recent activity</div>', unsafe_allow_html=True)
    history = state.get_history()

    if not history:
        render_empty_state(
            title="No activity yet",
            body="Generated quizzes will appear here for the rest of this session.",
            icon="🕘",
        )
        return

    sport_counts = Counter(q.sport.value for q in history)
    favorite_sport, favorite_count = sport_counts.most_common(1)[0]

    render_stat_row(
        [
            ("Favorite sport", f"{favorite_sport} ({favorite_count})"),
            ("Most attempted sport", favorite_sport),
        ]
    )
    st.caption("\"Attempted\" currently means \"generated\" — per-question attempt tracking isn't persisted yet.")

    st.write("")
    for quiz in history[:5]:
        st.markdown(
            f'<div class="quiz-history-item">{quiz.sport.value} — {quiz.difficulty.value} · '
            f'{len(quiz.questions)}Q · {quiz.generated_at.strftime("%H:%M:%S UTC")}</div>',
            unsafe_allow_html=True,
        )


def _render_quick_actions() -> None:
    st.markdown('<div class="quiz-eyebrow">Quick actions</div>', unsafe_allow_html=True)
    if st.button("⚡ Generate Quiz", use_container_width=True):
        state.set_active_section("Generate Quiz")
        st.rerun()
    if st.button("🕘 View History", use_container_width=True):
        state.set_active_section("Quiz History")
        st.rerun()
    if st.button("📚 Search Knowledge Base", use_container_width=True):
        state.set_active_section("Knowledge Base")
        st.rerun()


def _render_health_status(service: QuizService) -> None:
    st.markdown('<div class="quiz-eyebrow">Health status</div>', unsafe_allow_html=True)
    health = service.health_check()

    dot = {"ok": "#14b8a6", "degraded": "#ef4444", "unknown": "#a3a3a3"}
    cols = st.columns(len(health))
    for col, (component, (status, detail)) in zip(cols, health.items()):
        with col:
            st.markdown(
                f"""
                <div class="quiz-stat-card">
                    <div style="display:flex;align-items:center;gap:0.4rem;font-weight:600;font-size:0.9rem;">
                        <span style="width:8px;height:8px;border-radius:999px;background:{dot[status]};"></span>
                        {component}
                    </div>
                    <div class="quiz-stat-label">{detail}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Generate Quiz (the original main flow)
# ---------------------------------------------------------------------------

def _render_generate(sport: Sport, difficulty: Difficulty, question_count: int) -> None:
    st.title("Generate Quiz")
    st.caption(f"{sport.value} · {difficulty.value} · {question_count} questions")

    error = state.get_current_error()
    quiz = state.get_current_quiz()

    if error:
        render_error_state(error)
        return

    if quiz is None:
        render_empty_state()
        return

    render_quiz_header(quiz)
    for i, question in enumerate(quiz.questions, start=1):
        render_question_card(question, i)

    render_export_actions(quiz)


def handle_generation(
    service: QuizService, sport: Sport, difficulty: Difficulty, question_count: int
) -> None:
    """Runs the pipeline with a loading skeleton, and routes errors to user-facing messages."""
    placeholder = st.empty()
    with placeholder.container():
        st.subheader(f"{sport.value} - {difficulty.value}")
        render_loading_skeleton(question_count)

    request = GenerationRequest(sport=sport, difficulty=difficulty, question_count=question_count)

    try:
        quiz = service.generate(request)
        state.set_current_quiz(quiz)
    except NoContextAvailableError:
        state.set_current_error(
            "No grounding facts were found for this sport right now - "
            "try a different sport or try again shortly."
        )
    except (GenerationError, SchemaValidationError) as exc:
        state.set_current_error(str(exc))
    finally:
        placeholder.empty()


# ---------------------------------------------------------------------------
# Quiz History
# ---------------------------------------------------------------------------

def _render_history() -> None:
    st.title("Quiz History")
    st.caption("Quizzes generated this session (not persisted across restarts).")

    history = state.get_history()
    if not history:
        render_empty_state(
            title="No history yet",
            body="Generated quizzes will show up here for the rest of this session.",
            icon="🕘",
        )
        return

    for quiz in history:
        with st.container():
            st.markdown('<div class="quiz-card">', unsafe_allow_html=True)
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(
                    f"**{quiz.sport.value} — {quiz.difficulty.value}**  \n"
                    f"<span style='opacity:0.65;font-size:0.82rem;'>"
                    f"{len(quiz.questions)} questions · "
                    f"generated {quiz.generated_at.strftime('%H:%M:%S UTC')} · "
                    f"request `{quiz.request_id}`</span>",
                    unsafe_allow_html=True,
                )
            with col2:
                if st.button("Reopen", key=f"reopen_{quiz.request_id}", use_container_width=True):
                    state.set_current_quiz(quiz)
                    state.set_active_section("Generate Quiz")
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Analytics — derived only from real session history, nothing fabricated
# ---------------------------------------------------------------------------

def _render_analytics() -> None:
    st.title("Analytics")
    st.caption("Derived from quizzes generated in this session.")

    history: list[Quiz] = state.get_history()
    if not history:
        render_empty_state(
            title="Nothing to analyze yet",
            body="Generate a few quizzes and this page fills in with real numbers.",
            icon="📊",
        )
        return

    all_questions = [q for quiz in history for q in quiz.questions]
    avg_conf = round(100 * sum(q.confidence for q in all_questions) / len(all_questions))
    high_conf = sum(1 for q in all_questions if q.confidence >= 0.75)

    render_stat_row(
        [
            ("Total quizzes", str(len(history))),
            ("Total questions", str(len(all_questions))),
            ("Avg. confidence", f"{avg_conf}%"),
            ("High-confidence Qs", f"{high_conf}/{len(all_questions)}"),
        ]
    )

    st.write("")
    st.markdown('<div class="quiz-eyebrow">By sport</div>', unsafe_allow_html=True)
    by_sport: dict[str, int] = {}
    for quiz in history:
        by_sport[quiz.sport.value] = by_sport.get(quiz.sport.value, 0) + len(quiz.questions)
    st.bar_chart(by_sport)

    st.markdown('<div class="quiz-eyebrow" style="margin-top:1rem;">By difficulty</div>', unsafe_allow_html=True)
    by_difficulty: dict[str, int] = {}
    for quiz in history:
        by_difficulty[quiz.difficulty.value] = by_difficulty.get(quiz.difficulty.value, 0) + len(quiz.questions)
    st.bar_chart(by_difficulty)


# ---------------------------------------------------------------------------
# Knowledge Base — reads the real seed file, not a placeholder
# ---------------------------------------------------------------------------

def _render_knowledge_base() -> None:
    st.title("Knowledge Base")
    settings = get_settings()
    st.caption(f"Seed file: `{settings.sports_facts_path}` · retrieval top-k: {settings.local_retrieval_top_k}")

    try:
        with open(settings.sports_facts_path, "r", encoding="utf-8") as fh:
            facts = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        render_error_state(f"Could not read knowledge base file: {exc}")
        return

    if not facts:
        render_empty_state(title="Knowledge base is empty", body="No seed facts found.", icon="📚")
        return

    sports = sorted({f.get("sport", "Unknown") for f in facts})
    chosen = st.selectbox("Filter by sport", options=["All"] + sports)

    for fact in facts:
        if chosen != "All" and fact.get("sport") != chosen:
            continue
        st.markdown('<div class="quiz-card">', unsafe_allow_html=True)
        st.markdown(f"**{fact.get('sport', 'Unknown')}**")
        st.caption(fact.get("text") or fact.get("fact") or json.dumps(fact))
        st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Settings — real config values, read-only (change via .env, not fake toggles)
# ---------------------------------------------------------------------------

def _render_settings() -> None:
    st.title("Settings")
    st.caption("Read-only view of the active configuration. Change values via `.env` and restart.")

    settings = get_settings()

    st.markdown('<div class="quiz-eyebrow">Model</div>', unsafe_allow_html=True)
    render_stat_row(
        [
            ("Model", settings.gemini_model),
            ("Temperature", str(settings.llm_temperature)),
            ("Prompt version", settings.active_prompt_version),
        ]
    )

    st.write("")
    st.markdown('<div class="quiz-eyebrow">Retrieval & caching</div>', unsafe_allow_html=True)
    render_stat_row(
        [
            ("Local top-k", str(settings.local_retrieval_top_k)),
            ("Web top-k", str(settings.web_retrieval_top_k)),
            ("Max context tokens", str(settings.max_context_tokens)),
            ("Cache TTL", f"{settings.cache_ttl_seconds // 3600}h"),
        ]
    )


# ---------------------------------------------------------------------------
# About
# ---------------------------------------------------------------------------

def _render_about() -> None:
    st.title("About")
    st.markdown(
        """
        **Sports Quiz Agent** generates multiple-choice sports quizzes grounded
        in a local knowledge base (ChromaDB) and live web search (DuckDuckGo),
        with every question traceable to a source and scored for confidence.

        Pipeline: retrieval (local + web) → context compression → LLM
        generation (Gemini) → schema validation → disk cache.
        """
    )
    st.markdown(
        '<span class="quiz-badge quiz-badge-accent">No invented facts</span> '
        '<span class="quiz-badge quiz-badge-accent">Source-attributed</span> '
        '<span class="quiz-badge quiz-badge-accent">Confidence-scored</span>',
        unsafe_allow_html=True,
    )