"""Cycle/lead time percentiles per work item type."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass
class CycleTimePercentiles:
    work_item_type: str
    count: int
    cycle_time_p50: float | None
    cycle_time_p85: float | None
    cycle_time_p95: float | None
    lead_time_p50: float | None
    lead_time_p85: float | None
    lead_time_p95: float | None


def cycle_time_percentiles(
    conn: duckdb.DuckDBPyConnection, iteration_paths: list[str] | None = None
) -> list[CycleTimePercentiles]:
    where = ""
    params: list[str] = []
    if iteration_paths:
        placeholders = ",".join(["?"] * len(iteration_paths))
        where = f"WHERE iteration_path IN ({placeholders})"
        params = list(iteration_paths)

    rows = conn.execute(
        f"""
        SELECT
            work_item_type,
            COUNT(*) AS n,
            QUANTILE_CONT(cycle_time_days, 0.50) AS cycle_p50,
            QUANTILE_CONT(cycle_time_days, 0.85) AS cycle_p85,
            QUANTILE_CONT(cycle_time_days, 0.95) AS cycle_p95,
            QUANTILE_CONT(lead_time_days, 0.50) AS lead_p50,
            QUANTILE_CONT(lead_time_days, 0.85) AS lead_p85,
            QUANTILE_CONT(lead_time_days, 0.95) AS lead_p95
        FROM v_cycle_time
        {where}
        GROUP BY work_item_type
        ORDER BY work_item_type
        """,
        params,
    ).fetchall()
    return [
        CycleTimePercentiles(
            work_item_type=r[0], count=r[1],
            cycle_time_p50=r[2], cycle_time_p85=r[3], cycle_time_p95=r[4],
            lead_time_p50=r[5], lead_time_p85=r[6], lead_time_p95=r[7],
        )
        for r in rows
    ]
