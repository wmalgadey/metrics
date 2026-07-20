"""WorkTrackingSource port implementation — a thin facade over the REST and
Analytics OData clients."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import httpx

from ....config import AzureDevOpsConfig
from .odata import ODataClient
from .rest import RestClient


class AzdoWorkTrackingSource:
    def __init__(self, client: httpx.Client, cfg: AzureDevOpsConfig) -> None:
        self._rest = RestClient(client, cfg)
        self._odata = ODataClient(client, cfg)

    def list_iterations(self) -> list[dict[str, Any]]:
        return self._rest.list_iterations()

    def get_capacities(self, iteration_id: str) -> dict[str, Any]:
        return self._rest.get_capacities(iteration_id)

    def get_team_days_off(self, iteration_id: str) -> dict[str, Any]:
        return self._rest.get_team_days_off(iteration_id)

    def work_items(
        self, iteration_path: str, changed_since: date | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._odata.work_items(iteration_path, changed_since)

    def work_item_snapshots(
        self, iteration_path: str, date_from: date, date_to: date
    ) -> Iterator[dict[str, Any]]:
        return self._odata.work_item_snapshots(iteration_path, date_from, date_to)
