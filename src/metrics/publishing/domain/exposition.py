"""Render analytics domain points as Prometheus exposition lines with
historical timestamps. Pure — no I/O. Moved verbatim from the former
export/vm.py."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime

from ...analytics.domain.model import (
    BurndownPoint,
    BurndownSummaryPoint,
    CapacityDayPoint,
    CapacityPoint,
    CycleTimePercentiles,
    EffortBurndownPoint,
    ScopeChangePoint,
    VelocityPoint,
)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _sprint_label(iteration_path: str) -> str:
    """Azure DevOps iteration paths are backslash-separated. Dashboards
    (Perses) interpolate this label's raw value into PromQL/MetricsQL query
    text for the $sprint variable without escaping it for string-literal
    syntax, so a literal backslash breaks query parsing downstream. Forward
    slashes are unambiguous in that context and read just as naturally."""
    return iteration_path.replace("\\", "/")


def _line(metric: str, labels: dict[str, str], value: float, ts_ms: int) -> str:
    label_str = ",".join(f'{k}="{_escape_label(v)}"' for k, v in labels.items())
    return f"{metric}{{{label_str}}} {value} {ts_ms}"


def _day_ts_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def _date_ts_ms(d: date | None) -> int:
    """Sprint-summary samples sit at the sprint end date, capped at today
    (UTC): running/future sprints must not land in the future, outside the
    dashboard's [now - duration, now] window. Midnight (not now()) keeps
    repeated exports on the same day byte-identical."""
    today = datetime.now(tz=UTC).date()
    return _day_ts_ms(min(d, today) if d else today)


def render_burndown(points: Iterable[BurndownPoint], project: str, team: str) -> list[str]:
    lines = []
    for p in points:
        labels = {
            "project": project, "team": team,
            "sprint": _sprint_label(p.iteration_path), "work_item_type": p.work_item_type,
        }
        ts = _day_ts_ms(p.day)
        lines.append(_line("azdo_sprint_open_items", labels, p.open_items, ts))
        lines.append(_line("azdo_sprint_scope_items", labels, p.scope_items, ts))
        lines.append(_line("azdo_sprint_done_items", labels, p.done_items, ts))
        lines.append(_line("azdo_sprint_ideal_open_items", labels, p.ideal_open_items, ts))
        if p.remaining_effort is not None:
            lines.append(_line("azdo_sprint_remaining_effort", labels, p.remaining_effort, ts))
        if p.scope_effort is not None:
            lines.append(_line("azdo_sprint_scope_effort", labels, p.scope_effort, ts))
        if p.completed_effort is not None:
            lines.append(_line("azdo_sprint_completed_effort", labels, p.completed_effort, ts))
    return lines


def render_effort_burndown(
    points: Iterable[EffortBurndownPoint], project: str, team: str
) -> list[str]:
    """Effort series where missing item efforts are filled with estimates —
    published under `*_estimated` names so they never masquerade as the
    real-effort series."""
    lines = []
    for p in points:
        labels = {
            "project": project, "team": team,
            "sprint": _sprint_label(p.iteration_path), "work_item_type": p.work_item_type,
        }
        ts = _day_ts_ms(p.day)
        if p.remaining_effort is not None:
            lines.append(
                _line("azdo_sprint_remaining_effort_estimated", labels, p.remaining_effort, ts)
            )
        if p.scope_effort is not None:
            lines.append(_line("azdo_sprint_scope_effort_estimated", labels, p.scope_effort, ts))
        if p.completed_effort is not None:
            lines.append(
                _line("azdo_sprint_completed_effort_estimated", labels, p.completed_effort, ts)
            )
        lines.append(
            _line("azdo_sprint_effort_estimated_items", labels, p.estimated_items, ts)
        )
    return lines


def render_burndown_summary(
    points: Iterable[BurndownSummaryPoint], project: str, team: str
) -> list[str]:
    lines = []
    for p in points:
        labels = {
            "project": project, "team": team,
            "sprint": _sprint_label(p.iteration_path), "work_item_type": p.work_item_type,
        }
        ts = _date_ts_ms(p.end_date)
        lines.append(
            _line(
                "azdo_sprint_avg_burndown_items_per_day",
                labels, p.avg_burndown_items_per_day, ts,
            )
        )
    return lines


def render_capacity_daily(
    points: Iterable[CapacityDayPoint], project: str, team: str
) -> list[str]:
    lines = []
    for p in points:
        labels = {"project": project, "team": team, "sprint": _sprint_label(p.iteration_path)}
        ts = _day_ts_ms(p.day)
        lines.append(_line("azdo_sprint_capacity_day_hours", labels, p.capacity_hours, ts))
        lines.append(
            _line("azdo_sprint_remaining_capacity_hours", labels, p.remaining_capacity_hours, ts)
        )
    return lines


def render_velocity(points: Iterable[VelocityPoint], project: str, team: str) -> list[str]:
    lines = []
    for p in points:
        labels = {
            "project": project, "team": team,
            "sprint": _sprint_label(p.iteration_path), "work_item_type": p.work_item_type,
        }
        ts = _date_ts_ms(p.end_date)
        lines.append(_line("azdo_sprint_planned_items", labels, p.planned_items, ts))
        lines.append(_line("azdo_sprint_completed_items", labels, p.completed_items, ts))
        lines.append(
            _line("azdo_sprint_velocity_rolling_avg_items", labels, p.rolling_avg_items, ts)
        )
        if p.planned_effort is not None:
            lines.append(_line("azdo_sprint_velocity_planned_effort", labels, p.planned_effort, ts))
        if p.completed_effort is not None:
            lines.append(
                _line("azdo_sprint_velocity_completed_effort", labels, p.completed_effort, ts)
            )
    return lines


def render_capacity(points: Iterable[CapacityPoint], project: str, team: str) -> list[str]:
    lines = []
    for p in points:
        labels = {"project": project, "team": team, "sprint": _sprint_label(p.iteration_path)}
        ts = _date_ts_ms(p.end_date)
        lines.append(_line("azdo_sprint_capacity_hours", labels, p.capacity_hours, ts))
        if p.items_per_capacity_hour is not None:
            lines.append(
                _line("azdo_sprint_items_per_capacity_hour", labels, p.items_per_capacity_hour, ts)
            )
    return lines


def render_scope_change(
    points: Iterable[ScopeChangePoint], project: str, team: str
) -> list[str]:
    lines = []
    for p in points:
        labels = {
            "project": project, "team": team,
            "sprint": _sprint_label(p.iteration_path), "work_item_type": p.work_item_type,
        }
        ts = _date_ts_ms(p.end_date)
        lines.append(_line("azdo_sprint_added_mid_sprint_items", labels, p.added_items, ts))
        if p.scope_change_rate is not None:
            lines.append(_line("azdo_sprint_scope_change_rate", labels, p.scope_change_rate, ts))
        if p.completion_rate is not None:
            lines.append(_line("azdo_sprint_completion_rate", labels, p.completion_rate, ts))
    return lines


def render_cycle_time(
    percentiles: Iterable[CycleTimePercentiles], project: str, team: str
) -> list[str]:
    lines = []
    for p in percentiles:
        base_labels = {
            "project": project, "team": team,
            "sprint": _sprint_label(p.iteration_path), "work_item_type": p.work_item_type,
        }
        ts = _date_ts_ms(p.end_date)
        for quantile, cycle_val, lead_val in [
            ("0.5", p.cycle_time_p50, p.lead_time_p50),
            ("0.85", p.cycle_time_p85, p.lead_time_p85),
            ("0.95", p.cycle_time_p95, p.lead_time_p95),
        ]:
            labels = {**base_labels, "quantile": quantile}
            if cycle_val is not None:
                lines.append(_line("azdo_cycle_time_days", labels, cycle_val, ts))
            if lead_val is not None:
                lines.append(_line("azdo_lead_time_days", labels, lead_val, ts))
    return lines
