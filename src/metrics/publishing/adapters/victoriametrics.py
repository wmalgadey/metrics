"""MetricsSink port implementation — pushes exposition lines to
VictoriaMetrics' Prometheus-compatible import API."""

from __future__ import annotations

import httpx


def push_to_victoriametrics(url: str, lines: list[str], *, timeout: float = 30.0) -> None:
    if not lines:
        return
    payload = "\n".join(lines) + "\n"
    response = httpx.post(
        f"{url.rstrip('/')}/api/v1/import/prometheus", content=payload, timeout=timeout
    )
    response.raise_for_status()


class VictoriaMetricsSink:
    def __init__(self, url: str, *, timeout: float = 30.0) -> None:
        self._url = url
        self._timeout = timeout

    def push(self, lines: list[str]) -> None:
        push_to_victoriametrics(self._url, lines, timeout=self._timeout)
