"""
Session-state helpers.

Centralizes all st.session_state access behind named functions so the
shape of session state lives in one place. Views never touch
st.session_state directly.
"""

import streamlit as st

from src.schemas.quiz import Quiz

_QUIZ_KEY = "current_quiz"
_ERROR_KEY = "current_error"
_HISTORY_KEY = "recent_quizzes"
_MAX_HISTORY = 8


def init_state() -> None:
    """Call once at the top of app.py to ensure all keys exist."""
    if _QUIZ_KEY not in st.session_state:
        st.session_state[_QUIZ_KEY] = None
    if _ERROR_KEY not in st.session_state:
        st.session_state[_ERROR_KEY] = None
    if _HISTORY_KEY not in st.session_state:
        st.session_state[_HISTORY_KEY] = []


def get_current_quiz() -> Quiz | None:
    return st.session_state.get(_QUIZ_KEY)


def set_current_quiz(quiz: Quiz) -> None:
    st.session_state[_QUIZ_KEY] = quiz
    st.session_state[_ERROR_KEY] = None
    _push_history(quiz)


def get_current_error() -> str | None:
    return st.session_state.get(_ERROR_KEY)


def set_current_error(message: str) -> None:
    st.session_state[_ERROR_KEY] = message


def get_history() -> list[Quiz]:
    return st.session_state.get(_HISTORY_KEY, [])


def _push_history(quiz: Quiz) -> None:
    history = st.session_state.get(_HISTORY_KEY, [])
    history.insert(0, quiz)
    st.session_state[_HISTORY_KEY] = history[:_MAX_HISTORY]
