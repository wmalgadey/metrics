"""Per-sprint planned vs. completed item counts, with a rolling average."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass
class VelocityPoint:
    iteration_path: str
    work_item_type: str
    start_date: object
    end_date: object
    planned_items: int
    completed_items: int
    rolling_avg_items: float
    planned_effort: float | None = None
    completed_effort: float | None = None


def sprint_velocity(
    conn: duckdb.DuckDBPyConnection,
    iteration_paths: list[str],
    rolling_window: int,
) -> list[VelocityPoint]:
    if not iteration_paths:
        return []
    window = max(1, int(rolling_window))
    placeholders = ",".join(["?"] * len(iteration_paths))
    rows = conn.execute(
        f"""
        SELECT
            iteration_path, work_item_type, start_date, end_date,
            planned_items, completed_items, planned_effort, completed_effort,
            AVG(completed_items) OVER (
                PARTITION BY work_item_type ORDER BY start_date
                ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
            ) AS rolling_avg_items
        FROM v_velocity
        WHERE iteration_path IN ({placeholders})
        ORDER BY work_item_type, start_date
        """,
        iteration_paths,
    ).fetchall()
    return [
        VelocityPoint(
            iteration_path=r[0], work_item_type=r[1], start_date=r[2], end_date=r[3],
            planned_items=r[4], completed_items=r[5], planned_effort=r[6],
            completed_effort=r[7], rolling_avg_items=r[8],
        )
        for r in rows
    ]
