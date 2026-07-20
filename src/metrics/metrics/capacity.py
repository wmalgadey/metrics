"""Capacity vs. velocity: a normalized trend, not an absolute ratio
(capacity is hours/day, velocity is item counts — units differ)."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass
class CapacityPoint:
    iteration_path: str
    start_date: object
    end_date: object
    capacity_hours: float
    completed_items: int
    items_per_capacity_hour: float | None


def capacity_vs_velocity(
    conn: duckdb.DuckDBPyConnection, iteration_paths: list[str]
) -> list[CapacityPoint]:
    if not iteration_paths:
        return []
    placeholders = ",".join(["?"] * len(iteration_paths))
    rows = conn.execute(
        f"""
        WITH completed AS (
            SELECT iteration_path, SUM(completed_items) AS completed_items
            FROM v_velocity
            WHERE iteration_path IN ({placeholders})
            GROUP BY 1
        )
        SELECT
            i.path, i.start_date, i.end_date,
            COALESCE(c.capacity_hours, 0) AS capacity_hours,
            COALESCE(comp.completed_items, 0) AS completed_items
        FROM iterations i
        LEFT JOIN v_capacity c ON c.iteration_path = i.path
        LEFT JOIN completed comp ON comp.iteration_path = i.path
        WHERE i.path IN ({placeholders})
        ORDER BY i.start_date
        """,
        [*iteration_paths, *iteration_paths],
    ).fetchall()
    return [
        CapacityPoint(
            iteration_path=r[0], start_date=r[1], end_date=r[2],
            capacity_hours=r[3], completed_items=r[4],
            items_per_capacity_hour=(r[4] / r[3]) if r[3] else None,
        )
        for r in rows
    ]
