"""Azure DevOps Analytics OData client (WorkItems, WorkItemSnapshot).

All Analytics URLs and query construction live here so the preview API
version stays isolated in one place.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import httpx

from ..config import AzureDevOpsConfig
from .http import get_json

# $select lists are mandatory: unrestricted Analytics queries get rejected or
# throttled (VS403508-style warnings).
WORK_ITEM_FIELDS = [
    "WorkItemId",
    "Title",
    "WorkItemType",
    "State",
    "StateCategory",
    "CreatedDate",
    "ActivatedDate",
    "ClosedDate",
    "CompletedDate",
    "ChangedDate",
    "Effort",
    "StoryPoints",
    "RemainingWork",
    "CycleTimeDays",
    "LeadTimeDays",
    "ParentWorkItemId",
    "TagNames",
    "IterationSK",
]
SNAPSHOT_FIELDS = [
    "WorkItemId",
    "DateValue",
    "State",
    "StateCategory",
    "WorkItemType",
    "Effort",
    "RemainingWork",
    "IterationSK",
]


def _quote(value: str) -> str:
    """OData string literal: single quotes doubled."""
    return "'" + value.replace("'", "''") + "'"


class ODataClient:
    def __init__(self, client: httpx.Client, cfg: AzureDevOpsConfig) -> None:
        self._client = client
        self._base = cfg.analytics_url

    def _paged(self, entity: str, params: dict[str, str]) -> Iterator[dict[str, Any]]:
        url: str | None = f"{self._base}/{entity}"
        query: dict[str, str] | None = params
        while url:
            data = get_json(self._client, url, query)
            yield from data.get("value", [])
            url = data.get("@odata.nextLink")
            query = None  # nextLink already carries the full query string

    def work_items(
        self,
        iteration_path: str,
        changed_since: date | None = None,
    ) -> Iterator[dict[str, Any]]:
        filters = [f"Iteration/IterationPath eq {_quote(iteration_path)}"]
        if changed_since:
            filters.append(f"ChangedDate ge {changed_since.isoformat()}Z")
        return self._paged(
            "WorkItems",
            {
                "$select": ",".join(WORK_ITEM_FIELDS),
                "$filter": " and ".join(filters),
            },
        )

    def work_item_snapshots(
        self,
        iteration_path: str,
        date_from: date,
        date_to: date,
    ) -> Iterator[dict[str, Any]]:
        """Daily snapshots of every work item in the iteration — burndown backbone."""
        filters = [
            f"Iteration/IterationPath eq {_quote(iteration_path)}",
            f"DateValue ge {date_from.isoformat()}Z",
            f"DateValue le {date_to.isoformat()}Z",
        ]
        return self._paged(
            "WorkItemSnapshot",
            {
                "$select": ",".join(SNAPSHOT_FIELDS),
                "$filter": " and ".join(filters),
            },
        )
