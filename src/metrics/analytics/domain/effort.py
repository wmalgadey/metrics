"""Effort estimation for work items that carry no Effort value — pure, no DB.

The team's own estimates stay authoritative: estimation only fills the gaps,
and everything derived from it is exported as separate `*_estimated` series so
real and imputed effort remain distinguishable.

Heuristic, calibrated per work item type against the items that DO have an
Effort value:

1. `calibrated` — effort_per_task × task_count and/or effort_per_cycle_day ×
   cycle_time_days (median ratios over the calibration set); when both
   signals are available their estimates are averaged.
2. `type_median` — the type's median effort, when the item has no usable
   signal (no child tasks, not closed yet).
3. `default` — a configured constant, when the type has no calibration data
   at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median


@dataclass(frozen=True)
class EffortEstimationParams:
    """Tuning knobs, mapped from config.yaml's metrics.effort_estimation."""

    exclude_types: list[str] = field(default_factory=lambda: ["Task", "Improvement"])
    default_effort: float = 1.0


@dataclass(frozen=True)
class EffortSignal:
    """Per-item calibration/estimation input, as read from storage."""

    work_item_id: int
    work_item_type: str
    effort: float | None
    task_count: int
    cycle_time_days: float | None


@dataclass(frozen=True)
class EffortEstimate:
    work_item_id: int
    work_item_type: str
    effort: float
    source: str  # 'calibrated' | 'type_median' | 'default'


@dataclass(frozen=True)
class _Calibration:
    effort_per_task: float | None
    effort_per_cycle_day: float | None
    median_effort: float | None


def _calibrate(signals: list[EffortSignal]) -> dict[str, _Calibration]:
    by_type: dict[str, list[EffortSignal]] = {}
    for s in signals:
        if s.effort is not None and s.effort > 0:
            by_type.setdefault(s.work_item_type, []).append(s)

    calibrations: dict[str, _Calibration] = {}
    for work_item_type, samples in by_type.items():
        per_task = [s.effort / s.task_count for s in samples if s.task_count > 0]
        per_cycle = [
            s.effort / s.cycle_time_days
            for s in samples
            if s.cycle_time_days is not None and s.cycle_time_days > 0
        ]
        calibrations[work_item_type] = _Calibration(
            effort_per_task=median(per_task) if per_task else None,
            effort_per_cycle_day=median(per_cycle) if per_cycle else None,
            median_effort=median(s.effort for s in samples),
        )
    return calibrations


def estimate_missing_effort(
    signals: list[EffortSignal], params: EffortEstimationParams
) -> list[EffortEstimate]:
    """One estimate per item whose effort is unset and whose type is not
    excluded. Items with a real effort never get one."""
    calibrations = _calibrate(signals)

    estimates: list[EffortEstimate] = []
    for s in signals:
        if s.effort is not None or s.work_item_type in params.exclude_types:
            continue

        calibration = calibrations.get(s.work_item_type)
        candidates: list[float] = []
        if calibration is not None:
            if s.task_count > 0 and calibration.effort_per_task is not None:
                candidates.append(calibration.effort_per_task * s.task_count)
            if (
                s.cycle_time_days is not None
                and s.cycle_time_days > 0
                and calibration.effort_per_cycle_day is not None
            ):
                candidates.append(calibration.effort_per_cycle_day * s.cycle_time_days)

        if candidates:
            effort, source = sum(candidates) / len(candidates), "calibrated"
        elif calibration is not None and calibration.median_effort is not None:
            effort, source = calibration.median_effort, "type_median"
        else:
            effort, source = params.default_effort, "default"

        estimates.append(
            EffortEstimate(
                work_item_id=s.work_item_id, work_item_type=s.work_item_type,
                effort=effort, source=source,
            )
        )
    return estimates
