"""Shared httpx client with retry/backoff for Azure DevOps endpoints."""

from __future__ import annotations

import time
from typing import Any

import httpx

from .auth import auth_headers

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 4


class AzdoHttpError(RuntimeError):
    def __init__(self, response: httpx.Response) -> None:
        self.status_code = response.status_code
        detail = ""
        try:
            detail = response.json().get("message", "")
        except Exception:
            detail = response.text[:300]
        hint = ""
        if response.status_code in (401, 403):
            hint = " — check that AZDO_PAT is valid and has Work Items (Read) + Analytics (Read) scopes"
        elif response.status_code == 404:
            hint = " — check organization/project/team names in config.yaml"
        super().__init__(f"Azure DevOps request failed ({response.status_code}): {detail}{hint}")


def make_client(pat: str, timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(headers=auth_headers(pat), timeout=timeout, follow_redirects=True)


def get_json(client: httpx.Client, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET with retries on 429/5xx honoring Retry-After."""
    last: httpx.Response | None = None
    for attempt in range(MAX_RETRIES + 1):
        response = client.get(url, params=params)
        if response.status_code < 400:
            # A PAT that fails auth gets a 203 + HTML sign-in page from Azure DevOps.
            if response.status_code == 203 or "application/json" not in response.headers.get(
                "content-type", ""
            ):
                raise RuntimeError(
                    "Azure DevOps returned a non-JSON response — the PAT is likely "
                    "invalid or expired (set AZDO_PAT in .env)."
                )
            return response.json()
        if response.status_code not in RETRYABLE_STATUS or attempt == MAX_RETRIES:
            raise AzdoHttpError(response)
        retry_after = response.headers.get("Retry-After")
        delay = float(retry_after) if retry_after else 2.0**attempt
        time.sleep(min(delay, 60.0))
        last = response
    raise AzdoHttpError(last)  # pragma: no cover — loop always returns or raises
