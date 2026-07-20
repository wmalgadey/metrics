"""Export use case: render analytics metrics and push them to a sink.
`run_export` is a compat wrapper (same signature callers have always used)
that builds the DuckDB repository and VictoriaMetrics sink adapters and
delegates to `publish_metrics`, which depends only on the ports."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from ..analytics import service as analytics_service
from ..analytics.adapters.duckdb_repository import DuckDbSprintMetricsRepository
from ..analytics.ports import SprintMetricsRepository
from .adapters.victoriametrics import VictoriaMetricsSink
from .domain.exposition import render_burndown, render_capacity, render_cycle_time, render_velocity
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

    if sink is not None:
        sink.push(lines)

    return ExportSummary(iteration_paths=iteration_paths, line_count=len(lines))


def run_export(
    conn: duckdb.DuckDBPyConnection,
    *,
    project: str,
    team: str,
    iteration_paths: list[str],
    rolling_window: int,
    vm_url: str,
    push: bool = True,
) -> ExportSummary:
    """Compat entry point: builds the real repo/sink adapters and calls publish_metrics()."""
    repo = DuckDbSprintMetricsRepository(conn)
    sink = VictoriaMetricsSink(vm_url) if push else None
    return publish_metrics(
        repo, sink,
        project=project, team=team,
        iteration_paths=iteration_paths, rolling_window=rolling_window,
    )
