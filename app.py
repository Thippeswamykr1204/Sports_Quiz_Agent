"""
Streamlit entrypoint.

Intentionally thin: builds the QuizService once (cached across reruns via
st.cache_resource), seeds the local knowledge base on first run, then
delegates all rendering to src.ui.views. No business logic lives here.
"""

import streamlit as st

from src.config.settings import get_settings
from src.core.cache import DiskQuizCache
from src.core.logging import configure_logging
from src.core.metrics import ServiceMetrics
from src.core.migrations import apply_migrations
from src.repositories.attempt_repository import SQLiteAttemptRepository
from src.repositories.fact_repository import ChromaFactRepository
from src.repositories.history_repository import SQLiteHistoryRepository
from src.repositories.web_repository import DuckDuckGoWebRepository
from src.services.analytics_service import AnalyticsService
from src.services.history_service import HistoryService
from src.services.quiz_service import QuizService
from src.ui import state
from src.ui.theme import THEME_CSS
from src.ui.views import handle_generation, render_router, render_sidebar
from src.generation.gemini_client import GeminiLLMClient

st.set_page_config(page_title="Sports Quiz Agent", page_icon="🏆", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner="Setting up knowledge base...")
def build_service() -> QuizService:
    """Builds and wires all dependencies exactly once per server process."""
    settings = get_settings()
    configure_logging(log_level=settings.log_level, json_output=settings.environment != "development")

    fact_repository = ChromaFactRepository(persist_dir=settings.chroma_persist_dir)
    fact_repository.seed(settings.sports_facts_path)

    web_repository = DuckDuckGoWebRepository()

    llm_client = GeminiLLMClient(
        api_key=settings.google_api_key,
        model=settings.gemini_model,
        temperature=settings.llm_temperature,
        max_retries=settings.llm_max_retries,
    )

    cache = DiskQuizCache(cache_dir=settings.cache_dir)

    apply_migrations(settings.history_db_path)
    history_repository = SQLiteHistoryRepository(db_path=settings.history_db_path)
    history_service = HistoryService(repository=history_repository)
    attempt_repository = SQLiteAttemptRepository(db_path=settings.history_db_path)

    metrics = ServiceMetrics()
    analytics_service = AnalyticsService(
        history_service=history_service,
        attempt_repository=attempt_repository,
        metrics=metrics,
    )

    return QuizService(
        fact_repository=fact_repository,
        web_repository=web_repository,
        llm_client=llm_client,
        cache=cache,
        max_context_tokens=settings.max_context_tokens,
        prompt_version=settings.active_prompt_version,
        cache_ttl_seconds=settings.cache_ttl_seconds,
        local_top_k=settings.local_retrieval_top_k,
        web_top_k=settings.web_retrieval_top_k,
        history_service=history_service,
        attempt_repository=attempt_repository,
        analytics_service=analytics_service,
        metrics=metrics,
    )


def main() -> None:
    state.init_state()
    service = build_service()

    sport, difficulty, question_count, generate_clicked = render_sidebar()

    if generate_clicked:
        handle_generation(service, sport, difficulty, question_count)

    render_router(service, sport, difficulty, question_count)


if __name__ == "__main__":
    main()