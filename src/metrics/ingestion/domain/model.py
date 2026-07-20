"""Domain types for the ingestion context — plain dataclasses, no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class SyncResult:
    entity: str
    scope: str
    row_count: int
    status: str
    error: str | None = None


@dataclass
class IterationRecord:
    path: str
    iteration_id: str
    start_date: date | None
    end_date: date | None
    timeframe: str | None
