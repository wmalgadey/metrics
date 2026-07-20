"""Sprint burndown: daily open/scope/done item counts (+ optional effort) per
work item type, plus a calendar-aware ideal line."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb


@dataclass
class BurndownPoint:
    iteration_path: str
    work_item_type: str
    day: date
    open_items: int
    scope_items: int
    done_items: int
    ideal_open_items: float
    remaining_effort: float | None = None
    scope_effort: float | None = None
    completed_effort: float | None = None


def _working_days(
    conn: duckdb.DuckDBPyConnection, iteration_id: str, start: date, end: date
) -> list[date]:
    if start > end:
        return []
    rows = conn.execute(
        """
        SELECT d.day::DATE
        FROM generate_series(?::DATE, ?::DATE, INTERVAL 1 DAY) AS d(day)
        WHERE isodow(d.day) NOT IN (6, 7)
          AND NOT EXISTS (
              SELECT 1 FROM team_days_off t
              WHERE t.iteration_id = ? AND d.day BETWEEN t.start_date AND t.end_date
          )
        ORDER BY 1
        """,
        [start, end, iteration_id],
    ).fetchall()
    return [r[0] for r in rows]


def _ideal_line(
    day1: date, sprint_end: date, working_days: list[date], day1_scope: int
) -> dict[date, float]:
    """Linear ideal: day1_scope on day1, 0 on the last working day, flat over
    weekends/days off in between."""
    ideal: dict[date, float] = {}
    n = len(working_days)
    last_value = float(day1_scope)
    cursor = day1
    working_idx = 0
    while cursor <= sprint_end:
        if working_idx < n and working_days[working_idx] == cursor:
            if n > 1:
                last_value = day1_scope * (1 - working_idx / (n - 1))
            else:
                last_value = 0.0
            working_idx += 1
        ideal[cursor] = last_value
        cursor += timedelta(days=1)
    return ideal


def sprint_burndown(
    conn: duckdb.DuckDBPyConnection, iteration_path: str
) -> list[BurndownPoint]:
    iteration = conn.execute(
        "SELECT iteration_id, start_date, end_date FROM iterations WHERE path = ?",
        [iteration_path],
    ).fetchone()
    if iteration is None:
        return []
    iteration_id, start_date, end_date = iteration

    rows = conn.execute(
        """
        SELECT work_item_type, snapshot_date, open_items, scope_items, done_items,
               remaining_effort, scope_effort, completed_effort
        FROM v_sprint_burndown
        WHERE iteration_path = ?
        ORDER BY work_item_type, snapshot_date
        """,
        [iteration_path],
    ).fetchall()
    if not rows:
        return []

    by_type: dict[str, list[tuple]] = {}
    for row in rows:
        by_type.setdefault(row[0], []).append(row)

    points: list[BurndownPoint] = []
    for work_item_type, type_rows in by_type.items():
        day1 = type_rows[0][1]
        sprint_end = end_date or type_rows[-1][1]
        day1_scope = type_rows[0][3]
        working_days = _working_days(conn, iteration_id, day1, sprint_end)
        ideal = _ideal_line(day1, sprint_end, working_days, day1_scope)
        for _, day, open_items, scope_items, done_items, rem_eff, scope_eff, comp_eff in type_rows:
            points.append(
                BurndownPoint(
                    iteration_path=iteration_path,
                    work_item_type=work_item_type,
                    day=day,
                    open_items=open_items,
                    scope_items=scope_items,
                    done_items=done_items,
                    ideal_open_items=ideal.get(day, 0.0),
                    remaining_effort=rem_eff,
                    scope_effort=scope_eff,
                    completed_effort=comp_eff,
                )
            )
    return points
