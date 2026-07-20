"""Azure DevOps REST API 7.1 client: projects, teams, iterations, capacities, days off."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import AzureDevOpsConfig
from .http import get_json


class RestClient:
    def __init__(self, client: httpx.Client, cfg: AzureDevOpsConfig) -> None:
        self._client = client
        self._cfg = cfg
        self._api = {"api-version": cfg.api_version}

    def _team_url(self, path: str) -> str:
        c = self._cfg
        return f"{c.base_url}/{c.project}/{c.team}/_apis/{path}"

    def list_projects(self) -> list[dict[str, Any]]:
        """Also serves as PAT validation — fails fast on bad credentials."""
        data = get_json(self._client, f"{self._cfg.base_url}/_apis/projects", self._api)
        return data.get("value", [])

    def list_teams(self, project: str) -> list[dict[str, Any]]:
        url = f"{self._cfg.base_url}/_apis/projects/{project}/teams"
        return get_json(self._client, url, self._api).get("value", [])

    def list_iterations(self) -> list[dict[str, Any]]:
        """All iterations assigned to the configured team, with start/end dates."""
        url = self._team_url("work/teamsettings/iterations")
        return get_json(self._client, url, self._api).get("value", [])

    def get_capacities(self, iteration_id: str) -> dict[str, Any]:
        """Per-member capacities incl. activities and personal days off."""
        url = self._team_url(f"work/teamsettings/iterations/{iteration_id}/capacities")
        return get_json(self._client, url, self._api)

    def get_team_days_off(self, iteration_id: str) -> dict[str, Any]:
        url = self._team_url(f"work/teamsettings/iterations/{iteration_id}/teamdaysoff")
        return get_json(self._client, url, self._api)
