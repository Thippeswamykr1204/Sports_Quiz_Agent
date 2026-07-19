"""
In-process service metrics.

Deliberately minimal and in-memory: counters reset when the Streamlit
process restarts. This is honest for a single-process demo app - a
multi-worker deployment would need these pushed to a shared store
(Redis counter, Prometheus, etc). That's flagged as a Future
Enhancement below rather than faked with persistence this app doesn't
have.
"""

import time
from dataclasses import dataclass, field


@dataclass
class ServiceMetrics:
    """Real, process-lifetime counters - no synthetic/mocked numbers."""

    process_started_at: float = field(default_factory=time.monotonic)
    cache_hits: int = 0
    cache_misses: int = 0
    fresh_generations: int = 0
    total_generation_ms: float = 0.0

    def record_cache_hit(self) -> None:
        self.cache_hits += 1

    def record_fresh_generation(self, duration_ms: float) -> None:
        self.cache_misses += 1
        self.fresh_generations += 1
        self.total_generation_ms += duration_ms

    @property
    def total_quizzes_served(self) -> int:
        return self.cache_hits + self.cache_misses

    @property
    def cache_hit_rate(self) -> float | None:
        total = self.total_quizzes_served
        if total == 0:
            return None
        return self.cache_hits / total

    @property
    def avg_generation_ms(self) -> float | None:
        if self.fresh_generations == 0:
            return None
        return self.total_generation_ms / self.fresh_generations

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.process_started_at


# Future Enhancement: persist these to disk/Redis so restarts (and
# multi-worker deployments) don't reset the counters, and add a
# time-windowed view ("today" vs "all-time") backed by real timestamps
# instead of process-lifetime totals.