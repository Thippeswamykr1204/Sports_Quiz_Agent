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
from src.repositories.settings_repository import SQLiteSettingsRepository
from src.repositories.web_repository import DuckDuckGoWebRepository
from src.services.analytics_service import AnalyticsService
from src.services.history_service import HistoryService
from src.services.knowledge_service import KnowledgeService
from src.services.quiz_service import QuizService
from src.services.settings_service import SettingsService
from src.ui import state
from src.ui.theme import THEME_CSS, LIGHT_THEME_OVERRIDES_CSS
from src.ui.views import handle_generation, render_router, render_sidebar
from src.generation.gemini_client import GeminiLLMClient

st.set_page_config(page_title="Sports Quiz Agent", page_icon="🏆", layout="wide")


@st.cache_resource(show_spinner="Setting up knowledge base...")
def build_service() -> QuizService:
    """
    Builds and wires all dependencies exactly once per server process.

    Reads persisted user settings (Settings page) first, falling back to
    environment/.env config for anything not yet overridden. Changing a
    setting that affects this construction (model, temperature, prompt
    version, cache TTL) calls st.cache_resource.clear() + reruns so this
    function runs again with the new values - a full, real rebuild, not
    a partial patch.
    """
    settings = get_settings()

    apply_migrations(settings.history_db_path)
    settings_repository = SQLiteSettingsRepository(db_path=settings.history_db_path)
    settings_service = SettingsService(repository=settings_repository, env_settings=settings)
    resolved = settings_service.resolve()

    configure_logging(
        log_level=settings.log_level,
        json_output=settings.environment != "development",
        log_file_path=settings.log_file_path,
    )

    fact_repository = ChromaFactRepository(persist_dir=settings.chroma_persist_dir)
    fact_repository.seed(settings.sports_facts_path)

    web_repository = DuckDuckGoWebRepository()

    llm_client = GeminiLLMClient(
        api_key=settings.google_api_key,
        model=resolved.model,
        temperature=resolved.temperature,
        max_retries=settings.llm_max_retries,
    )

    cache = DiskQuizCache(cache_dir=settings.cache_dir)

    history_repository = SQLiteHistoryRepository(db_path=settings.history_db_path)
    history_service = HistoryService(repository=history_repository)
    attempt_repository = SQLiteAttemptRepository(db_path=settings.history_db_path)

    metrics = ServiceMetrics()
    analytics_service = AnalyticsService(
        history_service=history_service,
        attempt_repository=attempt_repository,
        metrics=metrics,
    )
    knowledge_service = KnowledgeService(fact_repository=fact_repository)

    return QuizService(
        fact_repository=fact_repository,
        web_repository=web_repository,
        llm_client=llm_client,
        cache=cache,
        max_context_tokens=settings.max_context_tokens,
        prompt_version=resolved.prompt_version,
        cache_ttl_seconds=int(resolved.cache_ttl_hours * 3600),
        local_top_k=settings.local_retrieval_top_k,
        web_top_k=settings.web_retrieval_top_k,
        history_service=history_service,
        attempt_repository=attempt_repository,
        analytics_service=analytics_service,
        metrics=metrics,
        knowledge_service=knowledge_service,
        settings_service=settings_service,
    )


def main() -> None:
    state.init_state()
    service = build_service()

    settings_service = service.get_settings_service()
    theme_mode = settings_service.get_theme() if settings_service else "Dark"
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    if theme_mode == "Light":
        st.markdown(LIGHT_THEME_OVERRIDES_CSS, unsafe_allow_html=True)

    max_questions = settings_service.get_max_questions() if settings_service else 6
    sport, difficulty, question_count, generate_clicked = render_sidebar(max_questions=max_questions)

    if generate_clicked:
        handle_generation(service, sport, difficulty, question_count)

    render_router(service, sport, difficulty, question_count)


if __name__ == "__main__":
    main()