from __future__ import annotations

from petcore.performance import PerformanceCounters, runtime_metrics


def test_performance_snapshot_has_all_required_fields() -> None:
    counters = PerformanceCounters()
    counters.inc("cpu_samples", 2)
    counters.inc("ui_updates", 3)
    counters.set_active_threads(4)
    snapshot = counters.snapshot()
    assert snapshot.cpu_samples == 2
    assert snapshot.ui_updates == 3
    assert snapshot.active_threads == 4
    assert snapshot.network_requests == 0


def test_performance_counters_reset_without_affecting_global() -> None:
    runtime_metrics.reset()
    runtime_metrics.inc("cache_hits")
    assert runtime_metrics.snapshot().cache_hits == 1
    runtime_metrics.reset()
    assert runtime_metrics.snapshot().cache_hits == 0
