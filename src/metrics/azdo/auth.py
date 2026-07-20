"""PAT authentication for Azure DevOps REST and Analytics APIs."""

from __future__ import annotations

import base64


class MissingPatError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "No Azure DevOps PAT configured. Set AZDO_PAT in .env or the environment "
            "(required scopes: Work Items Read, Analytics Read)."
        )


def auth_headers(pat: str) -> dict[str, str]:
    """Azure DevOps accepts a PAT as Basic auth with an empty username."""
    if not pat:
        raise MissingPatError()
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}
