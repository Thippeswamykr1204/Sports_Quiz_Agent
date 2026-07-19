"""
Reusable Streamlit render functions.

Each function is a pure "data in, UI out" component — no session_state
access here (that lives in ui/state.py), no business logic (that lives in
services/). Keeping this separation means the UI can be redesigned
without touching the pipeline, and vice versa.
"""

import streamlit as st

from src.schemas.quiz import Question, Quiz
from src.schemas.retrieval import SourceType


def render_confidence_badge(confidence: float) -> str:
    """Returns badge HTML for a confidence tier (high/med/low) — used inline in cards."""
    if confidence >= 0.75:
        tier, dot = "High confidence", "#14b8a6"
    elif confidence >= 0.45:
        tier, dot = "Medium confidence", "#eab308"
    else:
        tier, dot = "Low confidence", "#ef4444"
    return (
        f'<span class="quiz-badge quiz-badge-accent">'
        f'<span style="width:6px;height:6px;border-radius:999px;background:{dot};"></span>'
        f"{tier}</span>"
    )


def render_confidence_bar(confidence: float) -> None:
    """Renders a compact confidence indicator (0.0-1.0) as a labeled bar."""
    percent = round(confidence * 100)
    st.markdown(
        f"""
        <div class="quiz-confidence-row">
            <span>Confidence</span>
            <div class="quiz-confidence-bar-track">
                <div class="quiz-confidence-bar-fill" style="width:{percent}%;"></div>
            </div>
            <span>{percent}%</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_source_chips(question: Question) -> None:
    """Renders source chips (Local KB / Web article titles) below a question."""
    if not question.sources:
        return

    chips_html = ""
    for source in question.sources:
        label = "Local KB" if source.source_type == SourceType.LOCAL_KB else source.label
        chips_html += f'<span class="quiz-chip">{label}</span>'

    st.markdown(f'<div class="quiz-source-chips">{chips_html}</div>', unsafe_allow_html=True)


def render_question_card(question: Question, index: int) -> None:
    """Renders one full question card: text, options, reveal, confidence, sources."""
    st.markdown('<div class="quiz-card">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="quiz-card-question">Q{index}. {question.question} '
        f'{render_confidence_badge(question.confidence)}</div>',
        unsafe_allow_html=True,
    )

    choice_key = f"choice_{index}"
    reveal_key = f"reveal_{index}"

    option_labels = [f"{k}) {v}" for k, v in question.options.items()]
    selected = st.radio(
        "Choose an answer",
        options=option_labels,
        key=choice_key,
        label_visibility="collapsed",
        index=None,
    )

    if st.button("Check answer", key=f"check_{index}"):
        st.session_state[reveal_key] = True

    if st.session_state.get(reveal_key):
        if selected is None:
            st.warning("Pick an option first.")
        else:
            selected_letter = selected.split(")")[0]
            if selected_letter == question.correct_answer:
                st.success(f"Correct! {question.explanation}")
                st.toast("Correct answer", icon="✅")
            else:
                st.error(
                    f"Not quite — correct answer is {question.correct_answer}. "
                    f"{question.explanation}"
                )
                st.toast("Not quite", icon="⚠️")

    render_confidence_bar(question.confidence)
    render_source_chips(question)

    with st.expander("View grounding sources for this quiz"):
        if not question.sources:
            st.caption("No source attribution available.")
        for source in question.sources:
            label = "Local Knowledge Base" if source.source_type == SourceType.LOCAL_KB else source.label
            if source.url:
                st.markdown(f"**[{label}]({source.url})**")
            else:
                st.markdown(f"**{label}**")
            st.caption(source.excerpt)

    st.markdown("</div>", unsafe_allow_html=True)


def render_loading_skeleton(question_count: int = 3) -> None:
    """Renders shimmering placeholder cards while a quiz is generating."""
    for _ in range(question_count):
        st.markdown(
            """
            <div class="quiz-skeleton">
                <div class="quiz-skeleton-line" style="width: 70%;"></div>
                <div class="quiz-skeleton-line" style="width: 90%;"></div>
                <div class="quiz-skeleton-line" style="width: 40%;"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_empty_state(
    title: str = "Ready when you are",
    body: str = (
        "Pick a sport and difficulty in the sidebar, then generate a quiz. "
        "Every question is grounded in a local knowledge base and live web "
        "search — no invented facts."
    ),
    icon: str = "🎯",
) -> None:
    """Generic empty state — reused across Home / History / Analytics / KB tabs."""
    st.markdown(
        f"""
        <div class="quiz-glass" style="padding: 2.2rem 1.6rem; text-align: center; margin-bottom: 1rem;">
            <div style="font-size: 1.8rem; margin-bottom: 0.5rem;">{icon}</div>
            <div style="font-size: 1.1rem; font-weight: 600; margin-bottom: 0.4rem;">{title}</div>
            <div style="font-size: 0.88rem; opacity: 0.7; max-width: 440px; margin: 0 auto;">{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_card(label: str, value: str) -> None:
    """One KPI tile — used in Home/Analytics stat rows."""
    st.markdown(
        f"""
        <div class="quiz-stat-card">
            <div class="quiz-stat-value">{value}</div>
            <div class="quiz-stat-label">{label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_row(stats: list[tuple[str, str]]) -> None:
    """Renders a row of stat cards, one per (label, value) pair, via st.columns."""
    cols = st.columns(len(stats))
    for col, (label, value) in zip(cols, stats):
        with col:
            render_stat_card(label, value)


def render_nav_item(label: str, icon: str, active: bool = False) -> None:
    """Renders one sidebar nav row's label markup (button itself is a real st.button)."""
    css_class = "quiz-nav-item quiz-nav-item-active" if active else "quiz-nav-item"
    st.markdown(
        f'<div class="{css_class}"><span>{icon}</span><span>{label}</span></div>',
        unsafe_allow_html=True,
    )


def render_error_state(message: str) -> None:
    st.error(f"Couldn't generate a quiz: {message}")
    st.caption("Try again, or pick a different sport/difficulty.")


def render_quiz_header(quiz: Quiz) -> None:
    st.subheader(f"{quiz.sport.value} — {quiz.difficulty.value}")
    st.caption(
        f"Prompt version {quiz.prompt_version} · "
        f"generated {quiz.generated_at.strftime('%H:%M:%S UTC')} · "
        f"request `{quiz.request_id}`"
    )


def render_export_actions(quiz: Quiz) -> None:
    """Copy-as-Markdown and export-as-JSON actions for the current quiz."""
    col1, col2 = st.columns(2)

    markdown_lines = [f"# {quiz.sport.value} Quiz ({quiz.difficulty.value})\n"]
    for i, q in enumerate(quiz.questions, start=1):
        markdown_lines.append(f"**Q{i}. {q.question}**")
        for key, value in q.options.items():
            markdown_lines.append(f"- {key}) {value}")
        markdown_lines.append(f"\n*Correct answer: {q.correct_answer} — {q.explanation}*\n")
    markdown_text = "\n".join(markdown_lines)

    with col1:
        st.download_button(
            "Copy as Markdown",
            data=markdown_text,
            file_name=f"quiz_{quiz.sport.value.lower()}_{quiz.difficulty.value.lower()}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            "Export as JSON",
            data=quiz.model_dump_json(indent=2),
            file_name=f"quiz_{quiz.sport.value.lower()}_{quiz.difficulty.value.lower()}.json",
            mime="application/json",
            use_container_width=True,
        )