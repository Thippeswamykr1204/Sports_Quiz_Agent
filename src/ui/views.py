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
from src.repositories.history_repository import HistoryEntry
from src.schemas.quiz import Difficulty, GenerationRequest, Quiz, Sport
from src.services.history_service import HistoryService
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
    render_transparency_panel,
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
        _render_generate(service, sport, difficulty, question_count)
    elif section == "Quiz History":
        _render_history(service)
    elif section == "Analytics":
        _render_analytics(service)
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
        _render_recent_activity(service)
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
    history_service = service.get_history_service()
    session_history = state.get_history()
    all_questions = [q for quiz in session_history for q in quiz.questions]

    total_quizzes = (
        history_service.total_count() if history_service is not None else metrics.total_quizzes_served
    )

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
            ("Total quizzes", str(total_quizzes)),
            ("Avg. generation time", avg_gen),
            ("Avg. confidence", avg_conf),
            ("Cache hit rate", hit_rate),
            ("Knowledge base size", str(kb_size) if kb_size is not None else "unavailable"),
        ]
    )
    st.caption(
        "Total quizzes is the real persisted count (Quiz History DB). Generation time / "
        "cache hit rate are per-server-process since app start (see src/core/metrics.py)."
    )


def _render_recent_activity(service: QuizService) -> None:
    st.markdown('<div class="quiz-eyebrow">Recent activity</div>', unsafe_allow_html=True)
    history_service = service.get_history_service()

    if history_service is None:
        render_empty_state(
            title="History not configured",
            body="Quiz History persistence isn't wired up for this deployment.",
            icon="🕘",
        )
        return

    entries = history_service.search(sort_by="generated_at", sort_order="desc", limit=50)
    if not entries:
        render_empty_state(
            title="No activity yet",
            body="Generated quizzes will appear here once you generate your first one.",
            icon="🕘",
        )
        return

    sport_counts = Counter(e.sport for e in entries)
    favorite_sport, favorite_count = sport_counts.most_common(1)[0]

    render_stat_row(
        [
            ("Favorite sport", f"{favorite_sport} ({favorite_count})"),
            ("Most attempted sport", favorite_sport),
        ]
    )
    st.caption("\"Attempted\" currently means \"generated\" — per-question attempt tracking isn't persisted yet.")

    st.write("")
    for entry in entries[:5]:
        st.markdown(
            f'<div class="quiz-history-item">{entry.sport} — {entry.difficulty} · '
            f'{entry.question_count}Q · {entry.generated_at.strftime("%H:%M:%S UTC")}</div>',
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

def _render_generate(service: QuizService, sport: Sport, difficulty: Difficulty, question_count: int) -> None:
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
    attempt_repo = service.get_attempt_repository()

    def _record_attempt(question_index: int, is_correct: bool) -> None:
        if attempt_repo is not None:
            attempt_repo.record(
                request_id=quiz.request_id,
                sport=quiz.sport.value,
                difficulty=quiz.difficulty.value,
                question_index=question_index,
                is_correct=is_correct,
            )

    for i, question in enumerate(quiz.questions, start=1):
        render_question_card(question, i, on_answer_checked=_record_attempt)

    render_export_actions(quiz)

    trace = service.get_trace(quiz.request_id)
    if trace is not None:
        render_transparency_panel(trace)
    else:
        st.caption(
            "🔎 AI Transparency trace not available for this quiz (server restarted since "
            "generation, or it was reopened from history) — traces are in-memory only, "
            "see src/core/tracing.py."
        )


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

def _render_history(service: QuizService) -> None:
    st.title("Quiz History")
    history_service = service.get_history_service()

    if history_service is None:
        render_error_state("Quiz History persistence isn't configured for this deployment.")
        return

    st.caption(f"{history_service.total_count()} quizzes stored (persists across restarts).")

    # --- Search / filter / sort controls ---
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        search_text = st.text_input("Search question text", key="history_search", placeholder="e.g. 'World Cup'")
    with col2:
        sport_filter = st.selectbox("Sport", options=["All"] + [s.value for s in Sport], key="history_sport_filter")
    with col3:
        difficulty_filter = st.selectbox(
            "Difficulty", options=["All"] + [d.value for d in Difficulty], key="history_difficulty_filter"
        )
    with col4:
        sort_choice = st.selectbox(
            "Sort by",
            options=["Newest first", "Oldest first", "Highest confidence", "Lowest confidence"],
            key="history_sort",
        )

    sort_map = {
        "Newest first": ("generated_at", "desc"),
        "Oldest first": ("generated_at", "asc"),
        "Highest confidence": ("confidence_avg", "desc"),
        "Lowest confidence": ("confidence_avg", "asc"),
    }
    sort_by, sort_order = sort_map[sort_choice]

    entries = history_service.search(
        search_text=search_text or None,
        sport=None if sport_filter == "All" else sport_filter,
        difficulty=None if difficulty_filter == "All" else difficulty_filter,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=200,
    )

    st.write("")

    if not entries:
        render_empty_state(
            title="No matching quizzes",
            body="Adjust your search/filters, or generate a new quiz.",
            icon="🕘",
        )
        return

    for entry in entries:
        _render_history_row(service, history_service, entry)


def _render_history_row(service: QuizService, history_service: HistoryService, entry: HistoryEntry) -> None:
    st.markdown('<div class="quiz-card">', unsafe_allow_html=True)

    gen_time = f"{entry.generation_time_ms / 1000:.1f}s" if entry.generation_time_ms else "cached/unknown"
    st.markdown(
        f"**{entry.sport} — {entry.difficulty}** "
        f"{_confidence_badge_inline(entry.confidence_avg)}  \n"
        f"<span style='opacity:0.65;font-size:0.82rem;'>"
        f"{entry.question_count} questions · confidence {round(entry.confidence_avg * 100)}% · "
        f"generation {gen_time} · "
        f"generated {entry.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')} · "
        f"id `{entry.id[:8]}`</span>",
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        view_key = f"view_{entry.id}"
        if st.button("View details", key=view_key, use_container_width=True):
            st.session_state[f"history_expanded_{entry.id}"] = not st.session_state.get(
                f"history_expanded_{entry.id}", False
            )
    with col2:
        if st.button("Duplicate", key=f"dup_{entry.id}", use_container_width=True):
            new_id = history_service.duplicate(entry.id)
            if new_id:
                st.toast("Quiz duplicated", icon="🧬")
                st.rerun()
    with col3:
        full_quiz = history_service.export_json(entry.id)
        st.download_button(
            "Export JSON",
            data=full_quiz or "{}",
            file_name=f"quiz_{entry.sport.lower()}_{entry.id[:8]}.json",
            mime="application/json",
            key=f"export_{entry.id}",
            use_container_width=True,
        )
    with col4:
        if st.button("Delete", key=f"del_{entry.id}", use_container_width=True):
            history_service.delete(entry.id)
            st.toast("Quiz deleted", icon="🗑️")
            st.rerun()

    if st.session_state.get(f"history_expanded_{entry.id}", False):
        quiz = history_service.get_full_quiz(entry.id)
        if quiz is None:
            st.warning("This quiz's stored data could not be loaded.")
        else:
            with st.container():
                render_quiz_header(quiz)
                attempt_repo = service.get_attempt_repository()

                def _record_attempt(question_index: int, is_correct: bool, _quiz=quiz) -> None:
                    if attempt_repo is not None:
                        attempt_repo.record(
                            request_id=_quiz.request_id,
                            sport=_quiz.sport.value,
                            difficulty=_quiz.difficulty.value,
                            question_index=question_index,
                            is_correct=is_correct,
                        )

                for i, question in enumerate(quiz.questions, start=1):
                    render_question_card(question, i, on_answer_checked=_record_attempt)
                trace = service.get_trace(quiz.request_id)
                if trace is not None:
                    render_transparency_panel(trace)
                else:
                    st.caption("🔎 AI Transparency trace not available (in-memory only, not persisted with history).")
                if st.button("Open in Generate Quiz →", key=f"open_gen_{entry.id}"):
                    state.set_current_quiz(quiz)
                    state.set_active_section("Generate Quiz")
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def _confidence_badge_inline(confidence: float) -> str:
    if confidence >= 0.75:
        color = "#14b8a6"
    elif confidence >= 0.45:
        color = "#eab308"
    else:
        color = "#ef4444"
    return (
        f'<span class="quiz-badge quiz-badge-accent">'
        f'<span style="width:6px;height:6px;border-radius:999px;background:{color};"></span>'
        f"{round(confidence * 100)}%</span>"
    )


# ---------------------------------------------------------------------------
# Analytics — derived only from real session history, nothing fabricated
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Analytics — real data via AnalyticsService; every section is one small
# render function so each metric is independently swappable/testable.
# ---------------------------------------------------------------------------

def _render_analytics(service: QuizService) -> None:
    st.title("Analytics")
    analytics = service.get_analytics_service()

    if analytics is None:
        render_error_state("Analytics isn't configured for this deployment (needs History + Attempts persistence).")
        return

    total = analytics.quizzes_generated_total()
    st.caption(f"Derived from all {total} persisted quizzes and {analytics.total_attempts()} recorded answers.")

    if total == 0:
        render_empty_state(
            title="Nothing to analyze yet",
            body="Generate a few quizzes and this page fills in with real numbers.",
            icon="📊",
        )
        return

    _render_analytics_summary_cards(analytics)
    st.write("")
    _render_analytics_progress_indicators(analytics)
    st.write("")

    col_a, col_b = st.columns(2)
    with col_a:
        _render_analytics_trend(analytics, "daily")
    with col_b:
        _render_analytics_trend(analytics, "weekly")

    col_c, col_d = st.columns(2)
    with col_c:
        _render_analytics_distribution(analytics, "sport")
    with col_d:
        _render_analytics_distribution(analytics, "difficulty")

    st.write("")
    _render_analytics_retrieval_stats(analytics)

    st.write("")
    col_e, col_f = st.columns(2)
    with col_e:
        _render_analytics_performance(analytics)
    with col_f:
        _render_analytics_recent_activity(analytics)


def _render_analytics_summary_cards(analytics) -> None:
    """Quizzes generated / avg score / avg latency — the top-line numbers."""
    st.markdown('<div class="quiz-eyebrow">Summary</div>', unsafe_allow_html=True)

    avg_conf = analytics.avg_confidence()
    avg_latency = analytics.avg_latency_seconds()
    accuracy = analytics.accuracy_overall()

    render_stat_row(
        [
            ("Quizzes generated", str(analytics.quizzes_generated_total())),
            ("Avg. LLM confidence", f"{round(avg_conf * 100)}%" if avg_conf is not None else "—"),
            ("Avg. latency", f"{avg_latency:.1f}s" if avg_latency is not None else "—"),
            (
                "Avg. score (answers)",
                f"{round(accuracy * 100)}%" if accuracy is not None else "not enough data",
            ),
        ]
    )
    if accuracy is None:
        st.caption(
            "\"Avg. score\" needs answered questions, not just generated ones — "
            "answer some questions in Generate Quiz to populate this."
        )


def _render_analytics_progress_indicators(analytics) -> None:
    st.markdown('<div class="quiz-eyebrow">Progress indicators</div>', unsafe_allow_html=True)

    accuracy = analytics.accuracy_overall()
    hit_rate = analytics.cache_hit_rate()

    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"Overall accuracy — {round(accuracy * 100) if accuracy is not None else 0}%" + ("" if accuracy is not None else " (no answers recorded yet)"))
        st.progress(accuracy if accuracy is not None else 0.0)
    with col2:
        st.caption(f"Cache hit rate (this process) — {round(hit_rate * 100) if hit_rate is not None else 0}%" + ("" if hit_rate is not None else " (no requests yet)"))
        st.progress(hit_rate if hit_rate is not None else 0.0)


def _render_analytics_trend(analytics, granularity: str) -> None:
    label = "Daily trend" if granularity == "daily" else "Weekly trend"
    st.markdown(f'<div class="quiz-eyebrow">{label}</div>', unsafe_allow_html=True)
    points = analytics.daily_trend() if granularity == "daily" else analytics.weekly_trend()
    st.bar_chart({p.label: p.count for p in points})


def _render_analytics_distribution(analytics, by: str) -> None:
    label = "Sports popularity" if by == "sport" else "Difficulty distribution"
    st.markdown(f'<div class="quiz-eyebrow">{label}</div>', unsafe_allow_html=True)
    data = analytics.sports_popularity() if by == "sport" else analytics.difficulty_distribution()
    st.bar_chart(data)


def _render_analytics_retrieval_stats(analytics) -> None:
    st.markdown('<div class="quiz-eyebrow">Knowledge retrieval statistics</div>', unsafe_allow_html=True)
    stats = analytics.retrieval_stats()

    if stats["avg_chunks_used"] is None:
        st.caption(
            "No retrieval metadata recorded yet (quizzes generated before this feature "
            "shipped don't have it — architecture is in place, new quizzes populate it)."
        )
        return

    render_stat_row(
        [
            ("Avg. chunks retrieved", f"{stats['avg_chunks_used']:.1f}"),
            ("Avg. sources cited", f"{stats['avg_sources_used']:.1f}"),
            ("Data coverage", f"{round(stats['coverage'] * 100)}% of quizzes"),
        ]
    )


def _render_analytics_performance(analytics) -> None:
    st.markdown('<div class="quiz-eyebrow">Best performance / weakest category</div>', unsafe_allow_html=True)
    best = analytics.best_performance()
    worst = analytics.weakest_category()

    if best is None:
        render_empty_state(
            title="Not enough data yet",
            body="Answer questions across a few sports and this fills in with your strongest and weakest categories.",
            icon="🏆",
        )
        return

    render_stat_row(
        [
            ("Best: " + best.category, f"{round(best.accuracy * 100)}% ({best.attempts} answered)"),
            ("Weakest: " + worst.category, f"{round(worst.accuracy * 100)}% ({worst.attempts} answered)"),
        ]
    )


def _render_analytics_recent_activity(analytics) -> None:
    st.markdown('<div class="quiz-eyebrow">Recent activity</div>', unsafe_allow_html=True)
    for entry in analytics.recent_activity(limit=6):
        st.markdown(
            f'<div class="quiz-history-item">{entry.sport} — {entry.difficulty} · '
            f'{entry.question_count}Q · {entry.generated_at.strftime("%Y-%m-%d %H:%M UTC")}</div>',
            unsafe_allow_html=True,
        )


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