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

import os
import html
from collections import Counter

import streamlit as st

from src.config.settings import get_settings
from src.core.exceptions import GenerationError, NoContextAvailableError, SchemaValidationError
from src.repositories.history_repository import HistoryEntry
from src.schemas.quiz import Difficulty, GenerationRequest, Sport
from src.services.history_service import HistoryService
from src.services.knowledge_service import KnowledgeService
from src.services.quiz_service import QuizService
from src.services.settings_service import AVAILABLE_MODELS, SettingsService
from src.version import __version__
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

def render_sidebar(max_questions: int = 6) -> tuple[Sport, Difficulty, int, bool]:
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
    question_count = st.sidebar.slider(
        "Number of questions", min_value=1, max_value=max(max_questions, 1), value=min(3, max_questions)
    )

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
        _render_knowledge_base(service)
    elif section == "Settings":
        _render_settings(service)
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
    for col, (component, (status, detail)) in zip(cols, health.items(), strict=True):
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

    settings_service = service.get_settings_service()
    if settings_service is not None:
        threshold = settings_service.get_confidence_threshold()
        below = [i for i, q in enumerate(quiz.questions, start=1) if q.confidence < threshold]
        if below:
            st.warning(
                f"Question(s) {', '.join(str(i) for i in below)} scored below your confidence "
                f"threshold ({round(threshold * 100)}%) — set in Settings."
            )

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

# ---------------------------------------------------------------------------
# Knowledge Base Explorer — search/browse the real vector store, not the
# raw seed file. Doesn't expose collection name, persist path, distance
# metric, or raw embedding vectors — only the embedding id (opaque
# handle), real similarity scores, and stored metadata.
# ---------------------------------------------------------------------------

_KB_PAGE_SIZE = 8


def _render_knowledge_base(service: QuizService) -> None:
    st.title("Knowledge Base Explorer")
    knowledge = service.get_knowledge_service()

    if knowledge is None:
        render_error_state("Knowledge Base Explorer isn't configured for this deployment.")
        return

    try:
        options = knowledge.filter_options()
    except Exception as exc:
        render_error_state(f"Could not read the knowledge base: {exc}")
        return

    st.caption(f"{len(options['sports'])} sports · {len(options['sources'])} sources · {len(options['tags'])} tags indexed")

    query_text = st.text_input(
        "Search knowledge",
        key="kb_query",
        placeholder="e.g. '1983 world cup' — semantic search over embeddings, not just keyword match",
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        sport_filter = st.selectbox("Sport", options=["All"] + options["sports"], key="kb_sport_filter")
    with col2:
        source_filter = st.selectbox("Source", options=["All"] + options["sources"], key="kb_source_filter")
    with col3:
        tag_filter = st.selectbox("Tag", options=["All"] + options["tags"], key="kb_tag_filter") if options["tags"] else "All"
        if not options["tags"]:
            st.caption("No tags in this KB yet")
    with col4:
        date_range = st.text_input("Date (YYYY-MM-DD or range a..b)", key="kb_date_filter", placeholder="not set")

    date_from, date_to = _parse_kb_date_filter(date_range)

    filter_signature = (query_text, sport_filter, source_filter, tag_filter, date_range)
    if st.session_state.get("kb_filter_signature") != filter_signature:
        st.session_state["kb_filter_signature"] = filter_signature
        st.session_state["kb_page"] = 1

    sport_arg = None if sport_filter == "All" else sport_filter
    source_arg = None if source_filter == "All" else source_filter
    tag_arg = None if tag_filter == "All" else tag_filter

    st.write("")

    if query_text.strip():
        _render_kb_search_results(knowledge, query_text, sport_arg, source_arg, tag_arg, date_from, date_to)
    else:
        _render_kb_browse_results(knowledge, sport_arg, source_arg, tag_arg, date_from, date_to)


def _parse_kb_date_filter(raw: str) -> tuple[str | None, str | None]:
    """Accepts 'YYYY-MM-DD' or 'YYYY-MM-DD..YYYY-MM-DD'. Anything else is ignored (no filter)."""
    raw = raw.strip()
    if not raw:
        return None, None
    if ".." in raw:
        start, _, end = raw.partition("..")
        return (start.strip() or None), (end.strip() or None)
    return raw, raw


def _render_kb_search_results(
    knowledge: "KnowledgeService", query_text: str, sport, source, tag, date_from, date_to
) -> None:
    st.markdown('<div class="quiz-eyebrow">Search results — ranked by real embedding similarity</div>', unsafe_allow_html=True)
    try:
        chunks = knowledge.search(
            query_text, sport=sport, source=source, tag=tag, date_from=date_from, date_to=date_to, limit=20
        )
    except Exception as exc:
        render_error_state(f"Search failed: {exc}")
        return

    if not chunks:
        render_empty_state(title="No matches", body="Try a different query or loosen the filters.", icon="🔍")
        return

    for chunk in chunks:
        _render_kb_chunk_card(chunk)


def _render_kb_browse_results(knowledge: "KnowledgeService", sport, source, tag, date_from, date_to) -> None:
    page = st.session_state.get("kb_page", 1)
    result = knowledge.browse(
        sport=sport, source=source, tag=tag, date_from=date_from, date_to=date_to,
        page=page, page_size=_KB_PAGE_SIZE,
    )

    st.markdown(
        f'<div class="quiz-eyebrow">Browse — {result.total_count} chunks match these filters</div>',
        unsafe_allow_html=True,
    )

    if not result.chunks:
        render_empty_state(
            title="No chunks match these filters",
            body="Loosen a filter, or search instead of browsing.",
            icon="📚",
        )
        return

    for chunk in result.chunks:
        _render_kb_chunk_card(chunk)

    st.write("")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("← Prev", disabled=page <= 1, use_container_width=True):
            st.session_state["kb_page"] = page - 1
            st.rerun()
    with col2:
        st.markdown(
            f"<div style='text-align:center;opacity:0.7;font-size:0.85rem;padding-top:0.4rem;'>"
            f"Page {result.page} of {result.total_pages}</div>",
            unsafe_allow_html=True,
        )
    with col3:
        if st.button("Next →", disabled=page >= result.total_pages, use_container_width=True):
            st.session_state["kb_page"] = page + 1
            st.rerun()


def _render_kb_chunk_card(chunk) -> None:
    """
    Developer-tool-style chunk card: monospace embedding id, similarity
    bar (search mode only), metadata chips, truncated preview with an
    expander for the full document — never the raw embedding vector.
    """
    preview_limit = 220
    preview = chunk.text if len(chunk.text) <= preview_limit else chunk.text[:preview_limit].rstrip() + "…"
    preview = html.escape(preview)

    score_html = ""
    if chunk.similarity_score is not None:
        pct = round(chunk.similarity_score * 100)
        score_html = (
            f'<span class="quiz-badge quiz-badge-accent">{pct}% match</span>'
        )

    tag_chips = "".join(f'<span class="quiz-chip">#{html.escape(t)}</span>' for t in chunk.tags)
    date_chip = f'<span class="quiz-chip">{html.escape(chunk.date)}</span>' if chunk.date else ""

    st.markdown(
        f"""
        <div class="quiz-card">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-family:var(--quiz-mono);font-size:0.75rem;opacity:0.6;">id: {html.escape(chunk.embedding_id)}</span>
                {score_html}
            </div>
            <div style="margin:0.5rem 0 0.6rem;font-size:0.9rem;">{preview}</div>
            <div class="quiz-source-chips">
                <span class="quiz-chip">{html.escape(chunk.sport)}</span>
                <span class="quiz-chip">{html.escape(chunk.source)}</span>
                {date_chip}
                {tag_chips}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if len(chunk.text) > preview_limit:
        with st.expander("View full document"):
            st.write(chunk.text)


# ---------------------------------------------------------------------------
# Settings — real config values, read-only (change via .env, not fake toggles)
# ---------------------------------------------------------------------------

def _render_settings(service: QuizService) -> None:
    st.title("Settings")
    settings_service = service.get_settings_service()

    if settings_service is None:
        render_error_state("Settings persistence isn't configured for this deployment.")
        return

    if settings_service.has_any_overrides():
        st.caption("Some values below are overridden from your saved Settings; unset ones use the deployment's `.env` defaults.")
    else:
        st.caption("Showing deployment defaults from `.env` — nothing overridden yet.")

    resolved = settings_service.resolve()

    _render_settings_theme(settings_service, resolved)
    st.divider()
    _render_settings_model(settings_service, resolved)
    st.divider()
    _render_settings_cache(service, settings_service, resolved)
    st.divider()
    _render_settings_kb_management(service)
    st.divider()
    _render_settings_export_logs()
    st.divider()
    _render_settings_app_info()


def _render_settings_theme(settings_service: SettingsService, resolved) -> None:
    st.markdown('<div class="quiz-eyebrow">Theme</div>', unsafe_allow_html=True)
    theme = st.radio("Appearance", options=["Dark", "Light"], index=0 if resolved.theme == "Dark" else 1, horizontal=True)
    if theme != resolved.theme:
        settings_service.set_theme(theme)
        st.rerun()


def _render_settings_model(settings_service: SettingsService, resolved) -> None:
    st.markdown('<div class="quiz-eyebrow">Model & generation</div>', unsafe_allow_html=True)
    st.caption("Changing these rebuilds the generation pipeline — click Apply to take effect.")

    model_options = AVAILABLE_MODELS if resolved.model in AVAILABLE_MODELS else [resolved.model] + AVAILABLE_MODELS
    model = st.selectbox("Model selection", options=model_options, index=model_options.index(resolved.model))
    temperature = st.slider("Temperature", min_value=0.0, max_value=1.5, value=resolved.temperature, step=0.05)
    max_questions = st.slider("Maximum questions per quiz", min_value=1, max_value=10, value=resolved.max_questions)
    confidence_threshold = st.slider(
        "Confidence threshold", min_value=0.0, max_value=1.0, value=resolved.confidence_threshold, step=0.05,
        help="Questions below this confidence are flagged with a warning banner in Generate Quiz.",
    )
    prompt_version = st.selectbox(
        "Prompt version",
        options=settings_service.available_prompt_versions(),
        index=settings_service.available_prompt_versions().index(resolved.prompt_version),
    )

    if st.button("Apply & rebuild pipeline", type="primary"):
        settings_service.set_model(model)
        settings_service.set_temperature(temperature)
        settings_service.set_max_questions(max_questions)
        settings_service.set_confidence_threshold(confidence_threshold)
        settings_service.set_prompt_version(prompt_version)
        st.cache_resource.clear()
        st.toast("Settings saved — pipeline rebuilding", icon="⚙️")
        st.rerun()


def _render_settings_cache(service: QuizService, settings_service: SettingsService, resolved) -> None:
    st.markdown('<div class="quiz-eyebrow">Cache controls</div>', unsafe_allow_html=True)

    cache_ttl_hours = st.slider("Cache TTL (hours)", min_value=1, max_value=48, value=int(resolved.cache_ttl_hours))
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save TTL & rebuild", use_container_width=True):
            settings_service.set_cache_ttl_hours(float(cache_ttl_hours))
            st.cache_resource.clear()
            st.toast("Cache TTL saved", icon="⚙️")
            st.rerun()
    with col2:
        if st.button("Clear cache now", use_container_width=True):
            cache = service.get_cache()
            if cache is not None:
                removed = cache.clear()
                st.toast(f"Cleared {removed} cached quiz(zes)", icon="🧹")
            else:
                st.warning("No cache configured for this deployment.")


def _render_settings_kb_management(service: QuizService) -> None:
    st.markdown('<div class="quiz-eyebrow">Knowledge base management</div>', unsafe_allow_html=True)
    fact_repo = service.get_fact_repository()
    kb_size = service.get_kb_size()
    st.caption(f"Currently {kb_size if kb_size is not None else 'unknown'} facts stored.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Clear knowledge base", use_container_width=True):
            st.session_state["kb_clear_confirm"] = True
    with col2:
        if st.button("Reseed from data file", use_container_width=True):
            settings = get_settings()
            try:
                fact_repo.clear()
                inserted = fact_repo.seed(settings.sports_facts_path)
                st.toast(f"Reseeded {inserted} facts", icon="📚")
            except Exception as exc:
                st.error(f"Reseed failed: {exc}")

    if st.session_state.get("kb_clear_confirm"):
        st.warning("This deletes every fact in the knowledge base. Quizzes will have no local grounding until reseeded.")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Yes, clear it", type="primary", use_container_width=True):
                removed = fact_repo.clear()
                st.session_state["kb_clear_confirm"] = False
                st.toast(f"Removed {removed} facts", icon="🗑️")
                st.rerun()
        with col_b:
            if st.button("Cancel", use_container_width=True):
                st.session_state["kb_clear_confirm"] = False
                st.rerun()


def _render_settings_export_logs() -> None:
    st.markdown('<div class="quiz-eyebrow">Export logs</div>', unsafe_allow_html=True)
    settings = get_settings()
    log_path = settings.log_file_path

    if not log_path.exists():
        st.caption(
            f"No log file yet at `{log_path}` — it's created the first time the app logs something. "
            "Generate a quiz, then come back here."
        )
        return

    try:
        log_bytes = log_path.read_bytes()
    except OSError as exc:
        st.error(f"Could not read log file: {exc}")
        return

    st.caption(f"{log_path} — {len(log_bytes) / 1024:.1f} KB")
    st.download_button(
        "Export logs",
        data=log_bytes,
        file_name="sports_quiz_agent.log",
        mime="text/plain",
        use_container_width=False,
    )


def _render_settings_app_info() -> None:
    st.markdown('<div class="quiz-eyebrow">Application information</div>', unsafe_allow_html=True)
    settings = get_settings()
    build_time = os.environ.get("APP_BUILD_TIME")

    render_stat_row(
        [
            ("Version", __version__),
            ("Build time", build_time or "not set (APP_BUILD_TIME env var)"),
            ("Environment", settings.environment),
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