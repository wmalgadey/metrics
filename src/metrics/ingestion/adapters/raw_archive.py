"""Raw layer: verbatim API responses as gzipped JSON, for replay/audit.

Layout: {data_dir}/raw/{source}/{entity}/{run_id}/{scope_slug}.json.gz
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value).strip("-")
    return slug or "global"


def write_raw(
    data_dir: Path,
    source: str,
    entity: str,
    run_id: str,
    scope: str,
    payload: list[dict[str, Any]],
) -> Path:
    directory = data_dir / "raw" / source / entity / run_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slugify(scope)}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def read_raw(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def latest_run_files(data_dir: Path, source: str, entity: str) -> list[Path]:
    """All scope files from the most recent sync run for an entity, for --from-raw replay."""
    base = data_dir / "raw" / source / entity
    if not base.exists():
        return []
    runs = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
    if not runs:
        return []
    return sorted(runs[-1].glob("*.json.gz"))


class FileRawArchive:
    """RawArchive port implementation — binds data_dir and delegates to write_raw."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def write(
        self, source: str, entity: str, run_id: str, scope: str, payload: list[dict[str, Any]]
    ) -> Path:
        return write_raw(self._data_dir, source, entity, run_id, scope, payload)
