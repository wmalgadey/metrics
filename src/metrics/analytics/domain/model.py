"""Domain types for sprint analytics — plain dataclasses, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class IterationWindow:
    iteration_id: str
    start_date: date | None
    end_date: date | None


@dataclass
class BurndownRow:
    """One day's raw counts for one work item type, as read from storage."""

    work_item_type: str
    snapshot_date: date
    open_items: int
    scope_items: int
    done_items: int
    remaining_effort: float | None
    scope_effort: float | None
    completed_effort: float | None


@dataclass
class BurndownPoint:
    iteration_path: str
    work_item_type: str
    day: date
    open_items: int
    scope_items: int
    done_items: int
    ideal_open_items: float
    remaining_effort: float | None = None
    scope_effort: float | None = None
    completed_effort: float | None = None


@dataclass
class VelocityPoint:
    iteration_path: str
    work_item_type: str
    start_date: object
    end_date: object
    planned_items: int
    completed_items: int
    rolling_avg_items: float
    planned_effort: float | None = None
    completed_effort: float | None = None


@dataclass
class ScopeChangePoint:
    iteration_path: str
    work_item_type: str
    start_date: object
    end_date: object
    planned_items: int
    added_items: int
    final_scope_items: int
    completed_items: int
    scope_change_rate: float | None
    completion_rate: float | None


@dataclass
class EffortBurndownPoint:
    """Daily effort sums where items without a real Effort carry an estimated
    one (see domain/effort.py) — exported as separate `*_estimated` series.
    Sums are None for days/types with neither real nor estimated effort."""

    iteration_path: str
    work_item_type: str
    day: date
    remaining_effort: float | None
    scope_effort: float | None
    completed_effort: float | None
    estimated_items: int


@dataclass
class BurndownSummaryPoint:
    """Per-sprint roll-up backing the burndown dashboard's stat tiles —
    average items burned down per elapsed working day."""

    iteration_path: str
    work_item_type: str
    end_date: date | None
    avg_burndown_items_per_day: float


@dataclass
class CapacityDayPoint:
    """One sprint day's team capacity: hours available that day and hours
    still available from that day (inclusive) to the sprint end — the
    remaining-capacity line of the burndown chart."""

    iteration_path: str
    day: date
    capacity_hours: float
    remaining_capacity_hours: float


@dataclass
class CapacityPoint:
    iteration_path: str
    start_date: object
    end_date: object
    capacity_hours: float
    completed_items: int
    items_per_capacity_hour: float | None


@dataclass
class CycleTimePercentiles:
    iteration_path: str
    end_date: date | None
    work_item_type: str
    count: int
    cycle_time_p50: float | None
    cycle_time_p85: float | None
    cycle_time_p95: float | None
    lead_time_p50: float | None
    lead_time_p85: float | None
    lead_time_p95: float | None
