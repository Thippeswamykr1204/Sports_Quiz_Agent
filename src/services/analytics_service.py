"""
Analytics service - composes HistoryService + AttemptRepository (+
optional ServiceMetrics) into the real numbers the Analytics page shows.

Modular by design: each metric is one small pure function operating on
already-fetched entries/attempts, so the UI layer never touches SQL and
each metric can be unit-tested independently of Streamlit.

Every method returns None (or an empty structure) rather than a
fabricated value when there isn't enough data yet - see each
docstring for exactly what "not enough data" means for that metric.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.core.metrics import ServiceMetrics
from src.repositories.attempt_repository import AttemptEntry, AttemptRepository
from src.repositories.history_repository import HistoryEntry
from src.services.history_service import HistoryService


@dataclass(frozen=True)
class TrendPoint:
    label: str
    count: int


@dataclass(frozen=True)
class CategoryPerformance:
    category: str
    accuracy: float
    attempts: int


class AnalyticsService:
    def __init__(
        self,
        history_service: HistoryService,
        attempt_repository: AttemptRepository,
        metrics: ServiceMetrics | None = None,
    ) -> None:
        self._history_service = history_service
        self._attempt_repository = attempt_repository
        self._metrics = metrics

    # --- Volume ---------------------------------------------------------

    def quizzes_generated_total(self) -> int:
        return self._history_service.total_count()

    def daily_trend(self, days: int = 14, entries: list[HistoryEntry] | None = None) -> list[TrendPoint]:
        """Real count of quizzes generated per calendar day, oldest to newest."""
        entries = entries if entries is not None else self._all_entries()
        buckets: dict[str, int] = defaultdict(int)
        for e in entries:
            buckets[e.generated_at.date().isoformat()] += 1

        today = datetime.now(timezone.utc).date()
        points = []
        for i in range(days - 1, -1, -1):
            day = today - timedelta(days=i)
            points.append(TrendPoint(label=day.isoformat(), count=buckets.get(day.isoformat(), 0)))
        return points

    def weekly_trend(self, weeks: int = 8, entries: list[HistoryEntry] | None = None) -> list[TrendPoint]:
        """Real count of quizzes generated per ISO week, oldest to newest."""
        entries = entries if entries is not None else self._all_entries()
        buckets: dict[str, int] = defaultdict(int)
        for e in entries:
            iso_year, iso_week, _ = e.generated_at.isocalendar()
            buckets[f"{iso_year}-W{iso_week:02d}"] += 1

        today = datetime.now(timezone.utc).date()
        points = []
        for i in range(weeks - 1, -1, -1):
            week_date = today - timedelta(weeks=i)
            iso_year, iso_week, _ = week_date.isocalendar()
            label = f"{iso_year}-W{iso_week:02d}"
            points.append(TrendPoint(label=label, count=buckets.get(label, 0)))
        return points

    # --- Quality / performance ------------------------------------------

    def avg_confidence(self, entries: list[HistoryEntry] | None = None) -> float | None:
        """Average LLM-reported confidence across all generated quizzes."""
        entries = entries if entries is not None else self._all_entries()
        if not entries:
            return None
        return sum(e.confidence_avg for e in entries) / len(entries)

    def avg_latency_seconds(self, entries: list[HistoryEntry] | None = None) -> float | None:
        """Average generation latency. None entries (cache hits with no timing) are excluded."""
        entries = entries if entries is not None else self._all_entries()
        timed = [e.generation_time_ms for e in entries if e.generation_time_ms is not None]
        if not timed:
            return None
        return (sum(timed) / len(timed)) / 1000

    def accuracy_overall(self) -> float | None:
        """
        Real average correctness across all recorded answer checks.
        None means no attempts have been recorded yet (user hasn't
        answered any questions) - this is a distinct, honest state from
        "0% accuracy" and must be shown as such, not as 0%.
        """
        attempts = self._attempt_repository.list_all()
        if not attempts:
            return None
        return sum(1 for a in attempts if a.is_correct) / len(attempts)

    def accuracy_by_category(self, by: str = "sport") -> list[CategoryPerformance]:
        """
        Per-sport (or per-difficulty) accuracy from recorded attempts only.
        Empty list means no attempts recorded yet.
        """
        attempts = self._attempt_repository.list_all()
        buckets: dict[str, list[AttemptEntry]] = defaultdict(list)
        for a in attempts:
            key = a.sport if by == "sport" else a.difficulty
            buckets[key].append(a)

        return sorted(
            (
                CategoryPerformance(
                    category=key,
                    accuracy=sum(1 for a in group if a.is_correct) / len(group),
                    attempts=len(group),
                )
                for key, group in buckets.items()
            ),
            key=lambda c: c.accuracy,
            reverse=True,
        )

    def best_performance(self) -> CategoryPerformance | None:
        """Sport with the highest recorded accuracy. None if no attempts yet."""
        ranked = self.accuracy_by_category(by="sport")
        return ranked[0] if ranked else None

    def weakest_category(self) -> CategoryPerformance | None:
        """Sport with the lowest recorded accuracy. None if no attempts yet."""
        ranked = self.accuracy_by_category(by="sport")
        return ranked[-1] if ranked else None

    def total_attempts(self) -> int:
        return self._attempt_repository.count()

    # --- Distribution -----------------------------------------------------

    def sports_popularity(self, entries: list[HistoryEntry] | None = None) -> dict[str, int]:
        entries = entries if entries is not None else self._all_entries()
        counts: dict[str, int] = defaultdict(int)
        for e in entries:
            counts[e.sport] += 1
        return dict(counts)

    def difficulty_distribution(self, entries: list[HistoryEntry] | None = None) -> dict[str, int]:
        entries = entries if entries is not None else self._all_entries()
        counts: dict[str, int] = defaultdict(int)
        for e in entries:
            counts[e.difficulty] += 1
        return dict(counts)

    # --- Knowledge retrieval ----------------------------------------------

    def retrieval_stats(self, entries: list[HistoryEntry] | None = None) -> dict[str, float | int | None]:
        """
        Average chunks/sources used per generation. chunks_used/sources_count
        were added in migration v4 - quizzes generated before that upgrade
        have None for these columns, so `coverage` reports what fraction of
        stored quizzes actually have this data (honesty about partial data,
        not silently averaging over Nones as if they were zero).
        """
        entries = entries if entries is not None else self._all_entries()
        with_data = [e for e in entries if e.chunks_used is not None]
        if not with_data:
            return {"avg_chunks_used": None, "avg_sources_used": None, "coverage": 0.0, "sample_size": 0}

        return {
            "avg_chunks_used": sum(e.chunks_used for e in with_data) / len(with_data),
            "avg_sources_used": sum(e.sources_count or 0 for e in with_data) / len(with_data),
            "coverage": len(with_data) / len(entries),
            "sample_size": len(with_data),
        }

    # --- Activity -----------------------------------------------------------

    def recent_activity(self, limit: int = 10) -> list[HistoryEntry]:
        return self._history_service.search(sort_by="generated_at", sort_order="desc", limit=limit)

    def cache_hit_rate(self) -> float | None:
        """Process-lifetime cache hit rate, if metrics were supplied. See src/core/metrics.py."""
        if self._metrics is None:
            return None
        return self._metrics.cache_hit_rate

    # --- internal -----------------------------------------------------------

    def _all_entries(self) -> list[HistoryEntry]:
        return self._history_service.search(sort_by="generated_at", sort_order="desc", limit=5000)