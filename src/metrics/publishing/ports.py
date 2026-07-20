"""Port the publishing service depends on — implemented by a sink adapter."""

from __future__ import annotations

from typing import Protocol


class MetricsSink(Protocol):
    def push(self, lines: list[str]) -> None: ...
