"""Ports the ingestion service depends on — implemented by adapters."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from ..config import StatesConfig
from .domain.model import IterationRecord


class WorkTrackingSource(Protocol):
    def list_iterations(self) -> list[dict[str, Any]]: ...

    def get_capacities(self, iteration_id: str) -> dict[str, Any]: ...

    def get_team_days_off(self, iteration_id: str) -> dict[str, Any]: ...

    def work_items(
        self, iteration_path: str, changed_since: date | None = None
    ) -> Iterator[dict[str, Any]]: ...

    def work_item_snapshots(
        self, iteration_path: str, date_from: date, date_to: date
    ) -> Iterator[dict[str, Any]]: ...


class RawArchive(Protocol):
    def write(
        self, source: str, entity: str, run_id: str, scope: str, payload: list[dict[str, Any]]
    ) -> Path: ...


class SyncStore(Protocol):
    def upsert_project(self, project_id: str, organization: str) -> None: ...

    def upsert_team(self, team_id: str, project_id: str, name: str) -> None: ...

    def upsert_iterations(
        self,
        project_id: str,
        team_id: str,
        iterations: list[dict[str, Any]],
        selected_paths: set[str],
    ) -> int: ...

    def upsert_capacities(
        self, iteration_id: str, team_id: str, capacities: dict[str, Any]
    ) -> int: ...

    def upsert_team_days_off(
        self, iteration_id: str, team_id: str, team_days_off: dict[str, Any]
    ) -> int: ...

    def upsert_work_items(
        self,
        project_id: str,
        iteration_path: str,
        items: list[dict[str, Any]],
        states: StatesConfig,
    ) -> int: ...

    def upsert_work_item_snapshots(
        self, iteration_path: str, snapshots: list[dict[str, Any]], states: StatesConfig
    ) -> int: ...

    def known_iterations(self, team_id: str) -> list[IterationRecord]: ...

    def record_sync_log(
        self,
        *,
        run_id: str,
        started_at: datetime,
        finished_at: datetime | None,
        source: str,
        entity: str,
        scope: str,
        watermark: str | None,
        row_count: int,
        status: str,
        error: str | None = None,
        raw_path: str | None = None,
    ) -> None: ...

    def get_watermark(self, source: str, entity: str, scope: str) -> str | None: ...

    def recent_sync_runs(self, limit: int) -> list[tuple]: ...

    def local_iterations(self, team_id: str) -> list[tuple]: ...
