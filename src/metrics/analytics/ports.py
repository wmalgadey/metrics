"""Port the analytics service depends on — implemented by a storage adapter."""

from __future__ import annotations

from typing import Protocol

from .domain.calendar import DateRange
from .domain.model import (
    BurndownRow,
    CapacityPoint,
    CycleTimePercentiles,
    IterationWindow,
    ScopeChangePoint,
    VelocityPoint,
)


class SprintMetricsRepository(Protocol):
    def iteration_window(self, iteration_path: str) -> IterationWindow | None: ...

    def burndown_rows(self, iteration_path: str) -> list[BurndownRow]: ...

    def team_days_off(self, iteration_id: str) -> list[DateRange]: ...

    def velocity(self, iteration_paths: list[str], rolling_window: int) -> list[VelocityPoint]: ...

    def capacity_vs_velocity(self, iteration_paths: list[str]) -> list[CapacityPoint]: ...

    def cycle_time_percentiles(
        self, iteration_paths: list[str] | None = None
    ) -> list[CycleTimePercentiles]: ...

    def scope_change(self, iteration_paths: list[str]) -> list[ScopeChangePoint]: ...
