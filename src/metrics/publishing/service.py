"""Export use case: render analytics metrics and push them to a sink.
Depends only on the ports — the CLI composition root builds the concrete
repository/sink adapters (see cli.py) and calls publish_metrics() directly."""

from __future__ import annotations

from dataclasses import dataclass

from ..analytics import service as analytics_service
from ..analytics.ports import SprintMetricsRepository
from .domain.exposition import (
    render_burndown,
    render_capacity,
    render_cycle_time,
    render_scope_change,
    render_velocity,
)
from .ports import MetricsSink


@dataclass
class ExportSummary:
    iteration_paths: list[str]
    line_count: int


def publish_metrics(
    repo: SprintMetricsRepository,
    sink: MetricsSink | None,
    *,
    project: str,
    team: str,
    iteration_paths: list[str],
    rolling_window: int,
) -> ExportSummary:
    lines: list[str] = []
    for path in iteration_paths:
        lines += render_burndown(analytics_service.sprint_burndown(repo, path), project, team)

    lines += render_velocity(
        analytics_service.sprint_velocity(repo, iteration_paths, rolling_window), project, team
    )
    lines += render_capacity(
        analytics_service.capacity_vs_velocity(repo, iteration_paths), project, team
    )
    lines += render_cycle_time(
        analytics_service.cycle_time_percentiles(repo, iteration_paths), project, team
    )
    lines += render_scope_change(
        analytics_service.scope_change(repo, iteration_paths), project, team
    )

    if sink is not None:
        sink.push(lines)

    return ExportSummary(iteration_paths=iteration_paths, line_count=len(lines))
