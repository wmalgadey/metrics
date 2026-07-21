"""Unit tests for the pure effort-estimation heuristic (domain/effort.py)."""

import pytest

from metrics.analytics.domain.effort import (
    EffortEstimationParams,
    EffortSignal,
    estimate_missing_effort,
)

PBI = "Product Backlog Item"


def _sig(work_item_id, work_item_type=PBI, effort=None, tasks=0, cycle=None):
    return EffortSignal(
        work_item_id=work_item_id, work_item_type=work_item_type,
        effort=effort, task_count=tasks, cycle_time_days=cycle,
    )


def _estimate_for(estimates, work_item_id):
    return next(e for e in estimates if e.work_item_id == work_item_id)


def test_calibrated_by_task_count():
    signals = [
        _sig(1, effort=8.0, tasks=4),  # 2 effort/task
        _sig(2, effort=6.0, tasks=2),  # 3 effort/task -> median 2.5
        _sig(3, tasks=2),
    ]
    estimates = estimate_missing_effort(signals, EffortEstimationParams())
    e = _estimate_for(estimates, 3)
    assert e.effort == pytest.approx(5.0)
    assert e.source == "calibrated"


def test_calibrated_averages_task_and_cycle_signals():
    signals = [
        _sig(1, effort=8.0, tasks=4, cycle=4.0),  # 2 effort/task, 2 effort/cycle-day
        _sig(2, tasks=3, cycle=5.0),  # task -> 6, cycle -> 10, averaged -> 8
    ]
    estimates = estimate_missing_effort(signals, EffortEstimationParams())
    assert _estimate_for(estimates, 2).effort == pytest.approx(8.0)


def test_type_median_when_item_has_no_signals():
    signals = [
        _sig(1, effort=2.0, tasks=1),
        _sig(2, effort=8.0, tasks=1),
        _sig(3, effort=5.0, tasks=1),
        _sig(4),  # no tasks, not closed -> no signals
    ]
    estimates = estimate_missing_effort(signals, EffortEstimationParams())
    e = _estimate_for(estimates, 4)
    assert e.effort == pytest.approx(5.0)
    assert e.source == "type_median"


def test_default_when_type_has_no_calibration_data():
    signals = [_sig(1, work_item_type="Bug", tasks=3)]
    estimates = estimate_missing_effort(
        signals, EffortEstimationParams(default_effort=3.0)
    )
    e = _estimate_for(estimates, 1)
    assert e.effort == pytest.approx(3.0)
    assert e.source == "default"


def test_items_with_effort_and_excluded_types_get_no_estimate():
    signals = [
        _sig(1, effort=8.0, tasks=4),
        _sig(2, work_item_type="Task", tasks=1),
        _sig(3, work_item_type="Improvement", cycle=3.0),
    ]
    assert estimate_missing_effort(signals, EffortEstimationParams()) == []


def test_calibration_ignores_zero_effort_items():
    # effort=0 must not drag per-task ratios or the median toward zero
    signals = [
        _sig(1, effort=0.0, tasks=5),
        _sig(2, effort=6.0, tasks=2),
        _sig(3, tasks=1),
    ]
    estimates = estimate_missing_effort(signals, EffortEstimationParams())
    assert _estimate_for(estimates, 3).effort == pytest.approx(3.0)
