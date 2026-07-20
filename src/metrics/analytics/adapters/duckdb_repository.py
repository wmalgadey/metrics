"""DuckDB implementation of SprintMetricsRepository — the only place in the
analytics context that speaks SQL. Bodies are unchanged from the pre-refactor
metrics.metrics.{burndown,velocity,capacity,cycletime} modules."""

from __future__ import annotations

import duckdb

from ..domain.calendar import DateRange
from ..domain.model import (
    BurndownRow,
    CapacityPoint,
    CycleTimePercentiles,
    IterationWindow,
    ScopeChangePoint,
    VelocityPoint,
)


class DuckDbSprintMetricsRepository:
    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def iteration_window(self, iteration_path: str) -> IterationWindow | None:
        row = self._conn.execute(
            "SELECT iteration_id, start_date, end_date FROM iterations WHERE path = ?",
            [iteration_path],
        ).fetchone()
        if row is None:
            return None
        return IterationWindow(iteration_id=row[0], start_date=row[1], end_date=row[2])

    def burndown_rows(self, iteration_path: str) -> list[BurndownRow]:
        rows = self._conn.execute(
            """
            SELECT work_item_type, snapshot_date, open_items, scope_items, done_items,
                   remaining_effort, scope_effort, completed_effort
            FROM v_sprint_burndown
            WHERE iteration_path = ?
            ORDER BY work_item_type, snapshot_date
            """,
            [iteration_path],
        ).fetchall()
        return [
            BurndownRow(
                work_item_type=r[0], snapshot_date=r[1], open_items=r[2], scope_items=r[3],
                done_items=r[4], remaining_effort=r[5], scope_effort=r[6], completed_effort=r[7],
            )
            for r in rows
        ]

    def team_days_off(self, iteration_id: str) -> list[DateRange]:
        rows = self._conn.execute(
            "SELECT start_date, end_date FROM team_days_off WHERE iteration_id = ?",
            [iteration_id],
        ).fetchall()
        return [DateRange(start=r[0], end=r[1]) for r in rows]

    def velocity(self, iteration_paths: list[str], rolling_window: int) -> list[VelocityPoint]:
        if not iteration_paths:
            return []
        window = max(1, int(rolling_window))
        placeholders = ",".join(["?"] * len(iteration_paths))
        rows = self._conn.execute(
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

    def capacity_vs_velocity(self, iteration_paths: list[str]) -> list[CapacityPoint]:
        if not iteration_paths:
            return []
        placeholders = ",".join(["?"] * len(iteration_paths))
        rows = self._conn.execute(
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

    def scope_change(self, iteration_paths: list[str]) -> list[ScopeChangePoint]:
        if not iteration_paths:
            return []
        placeholders = ",".join(["?"] * len(iteration_paths))
        rows = self._conn.execute(
            f"""
            WITH bounds AS (
                SELECT iteration_path, MAX(snapshot_date) AS last_day
                FROM work_item_snapshots
                GROUP BY 1
            )
            SELECT
                sc.iteration_path, sc.work_item_type, sc.start_date, sc.end_date,
                sc.planned_items, sc.added_items, lb.scope_items AS final_scope_items,
                v.completed_items
            FROM v_scope_change sc
            JOIN bounds b ON b.iteration_path = sc.iteration_path
            JOIN v_sprint_burndown lb
                ON lb.iteration_path = sc.iteration_path
                AND lb.snapshot_date = b.last_day
                AND lb.work_item_type = sc.work_item_type
            JOIN v_velocity v
                ON v.iteration_path = sc.iteration_path
                AND v.work_item_type = sc.work_item_type
            WHERE sc.iteration_path IN ({placeholders})
            ORDER BY sc.work_item_type, sc.start_date
            """,
            iteration_paths,
        ).fetchall()
        points = []
        for r in rows:
            planned_items, added_items, final_scope_items, completed_items = r[4], r[5], r[6], r[7]
            total_items = planned_items + added_items
            points.append(
                ScopeChangePoint(
                    iteration_path=r[0], work_item_type=r[1], start_date=r[2], end_date=r[3],
                    planned_items=planned_items, added_items=added_items,
                    final_scope_items=final_scope_items, completed_items=completed_items,
                    scope_change_rate=(added_items / total_items) if total_items else None,
                    completion_rate=(
                        completed_items / final_scope_items if final_scope_items else None
                    ),
                )
            )
        return points

    def cycle_time_percentiles(
        self, iteration_paths: list[str] | None = None
    ) -> list[CycleTimePercentiles]:
        where = ""
        params: list[str] = []
        if iteration_paths:
            placeholders = ",".join(["?"] * len(iteration_paths))
            where = f"WHERE ct.iteration_path IN ({placeholders})"
            params = list(iteration_paths)

        rows = self._conn.execute(
            f"""
            SELECT
                ct.iteration_path,
                MAX(i.end_date) AS end_date,
                ct.work_item_type,
                COUNT(*) AS n,
                QUANTILE_CONT(ct.cycle_time_days, 0.50) AS cycle_p50,
                QUANTILE_CONT(ct.cycle_time_days, 0.85) AS cycle_p85,
                QUANTILE_CONT(ct.cycle_time_days, 0.95) AS cycle_p95,
                QUANTILE_CONT(ct.lead_time_days, 0.50) AS lead_p50,
                QUANTILE_CONT(ct.lead_time_days, 0.85) AS lead_p85,
                QUANTILE_CONT(ct.lead_time_days, 0.95) AS lead_p95
            FROM v_cycle_time ct
            LEFT JOIN iterations i ON i.path = ct.iteration_path
            {where}
            GROUP BY ct.iteration_path, ct.work_item_type
            ORDER BY ct.iteration_path, ct.work_item_type
            """,
            params,
        ).fetchall()
        return [
            CycleTimePercentiles(
                iteration_path=r[0], end_date=r[1], work_item_type=r[2], count=r[3],
                cycle_time_p50=r[4], cycle_time_p85=r[5], cycle_time_p95=r[6],
                lead_time_p50=r[7], lead_time_p85=r[8], lead_time_p95=r[9],
            )
            for r in rows
        ]
