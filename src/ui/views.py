"""
Top-level view composition.

render_sidebar() and render_main() are the only two functions app.py
calls. Everything here is composition: pulling state (ui/state.py),
rendering components (ui/components.py), and calling the service layer
(services/quiz_service.py) - no direct chromadb/openai/duckduckgo access.
"""

import streamlit as st

from src.core.exceptions import GenerationError, NoContextAvailableError, SchemaValidationError
from src.schemas.quiz import Difficulty, GenerationRequest, Sport
from src.services.quiz_service import QuizService
from src.ui import state
from src.ui.components import (
    render_empty_state,
    render_error_state,
    render_export_actions,
    render_loading_skeleton,
    render_question_card,
    render_quiz_header,
)


def render_sidebar() -> tuple[Sport, Difficulty, int, bool]:
    """Renders sidebar controls and recent-quiz history. Returns the current selections."""
    st.sidebar.header("Quiz Settings")

    sport = st.sidebar.selectbox("Sport", options=list(Sport), format_func=lambda s: s.value)
    difficulty = st.sidebar.select_slider(
        "Difficulty", options=list(Difficulty), format_func=lambda d: d.value
    )
    question_count = st.sidebar.slider("Number of questions", min_value=1, max_value=6, value=3)

    generate_clicked = st.sidebar.button(
        "Generate Fresh Quiz", use_container_width=True, type="primary"
    )

    _render_history_sidebar()

    return sport, difficulty, question_count, generate_clicked


def _render_history_sidebar() -> None:
    history = state.get_history()
    if not history:
        return

    st.sidebar.divider()
    st.sidebar.caption("Recent quizzes")
    for quiz in history:
        label = f"{quiz.sport.value} - {quiz.difficulty.value}"
        if st.sidebar.button(label, key=f"history_{quiz.request_id}", use_container_width=True):
            state.set_current_quiz(quiz)


def render_main(service: QuizService, sport: Sport, difficulty: Difficulty, question_count: int) -> None:
    """Renders the main content area: empty/loading/error/quiz states."""
    st.title("Sports Quiz Generator")
    st.caption(
        "Grounded in a local knowledge base and live web search - every question "
        "is traceable to its source, never invented."
    )

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
