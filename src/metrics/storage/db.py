"""DuckDB connection management. `sync` is the only writer; the dashboard
export step and any ad-hoc analysis should open read-only connections."""

from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: Path, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path), read_only=read_only)
    if not read_only:
        apply_schema(conn)
    return conn


def apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
