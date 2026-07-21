"""Sprint analytics use cases — compose domain logic against a repository port."""

from __future__ import annotations

from .domain.burndown import ideal_line
from .domain.calendar import working_days
from .domain.model import (
    BurndownPoint,
    BurndownSummaryPoint,
    CapacityDayPoint,
    CapacityPoint,
    CycleTimePercentiles,
    ScopeChangePoint,
    VelocityPoint,
)
from .ports import SprintMetricsRepository


def sprint_burndown(
    repo: SprintMetricsRepository, iteration_path: str
) -> list[BurndownPoint]:
    window = repo.iteration_window(iteration_path)
    if window is None:
        return []

    rows = repo.burndown_rows(iteration_path)
    if not rows:
        return []

    days_off = repo.team_days_off(window.iteration_id)

    by_type: dict[str, list] = {}
    for row in rows:
        by_type.setdefault(row.work_item_type, []).append(row)

    points: list[BurndownPoint] = []
    for work_item_type, type_rows in by_type.items():
        day1 = type_rows[0].snapshot_date
        sprint_end = window.end_date or type_rows[-1].snapshot_date
        day1_scope = type_rows[0].scope_items
        wdays = working_days(day1, sprint_end, days_off)
        ideal = ideal_line(day1, sprint_end, wdays, day1_scope)
        for row in type_rows:
            points.append(
                BurndownPoint(
                    iteration_path=iteration_path,
                    work_item_type=work_item_type,
                    day=row.snapshot_date,
                    open_items=row.open_items,
                    scope_items=row.scope_items,
                    done_items=row.done_items,
                    ideal_open_items=ideal.get(row.snapshot_date, 0.0),
                    remaining_effort=row.remaining_effort,
                    scope_effort=row.scope_effort,
                    completed_effort=row.completed_effort,
                )
            )
    return points


def sprint_burndown_summary(
    repo: SprintMetricsRepository, iteration_path: str
) -> list[BurndownSummaryPoint]:
    """Average burndown per work item type: items completed so far divided by
    the working days elapsed between day 1 and the latest snapshot (both
    inclusive) — the 'Average burndown' stat of an Azure DevOps sprint chart."""
    window = repo.iteration_window(iteration_path)
    if window is None:
        return []

    rows = repo.burndown_rows(iteration_path)
    if not rows:
        return []

    days_off = repo.team_days_off(window.iteration_id)

    by_type: dict[str, list] = {}
    for row in rows:
        by_type.setdefault(row.work_item_type, []).append(row)

    points: list[BurndownSummaryPoint] = []
    for work_item_type, type_rows in by_type.items():
        day1 = type_rows[0].snapshot_date
        last = type_rows[-1]
        elapsed = len(working_days(day1, last.snapshot_date, days_off))
        points.append(
            BurndownSummaryPoint(
                iteration_path=iteration_path,
                work_item_type=work_item_type,
                end_date=last.snapshot_date,
                avg_burndown_items_per_day=(last.done_items / elapsed) if elapsed else 0.0,
            )
        )
    return points


def sprint_capacity_daily(
    repo: SprintMetricsRepository, iteration_path: str
) -> list[CapacityDayPoint]:
    return repo.capacity_daily(iteration_path)


def sprint_velocity(
    repo: SprintMetricsRepository, iteration_paths: list[str], rolling_window: int
) -> list[VelocityPoint]:
    return repo.velocity(iteration_paths, rolling_window)


def capacity_vs_velocity(
    repo: SprintMetricsRepository, iteration_paths: list[str]
) -> list[CapacityPoint]:
    return repo.capacity_vs_velocity(iteration_paths)


def cycle_time_percentiles(
    repo: SprintMetricsRepository, iteration_paths: list[str] | None = None
) -> list[CycleTimePercentiles]:
    return repo.cycle_time_percentiles(iteration_paths)


def scope_change(
    repo: SprintMetricsRepository, iteration_paths: list[str]
) -> list[ScopeChangePoint]:
    return repo.scope_change(iteration_paths)
