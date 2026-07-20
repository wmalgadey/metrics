"""DuckDbSyncStore: the SyncStore port implementation. Transforms fetched
Azure DevOps data into DuckDB tables (idempotent upserts)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import duckdb

from ...config import StatesConfig
from ..domain.model import IterationRecord
from ..domain.states import classify_state


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _date(value: str | None):
    ts = _ts(value)
    return ts.date() if ts else None


def upsert_project(conn: duckdb.DuckDBPyConnection, project_id: str, organization: str) -> None:
    conn.execute(
        """
        INSERT INTO projects (project_id, organization) VALUES (?, ?)
        ON CONFLICT (project_id) DO UPDATE SET organization = excluded.organization
        """,
        [project_id, organization],
    )


def upsert_team(
    conn: duckdb.DuckDBPyConnection, team_id: str, project_id: str, name: str
) -> None:
    conn.execute(
        """
        INSERT INTO teams (team_id, project_id, name) VALUES (?, ?, ?)
        ON CONFLICT (team_id) DO UPDATE SET name = excluded.name
        """,
        [team_id, project_id, name],
    )


def upsert_iterations(
    conn: duckdb.DuckDBPyConnection,
    project_id: str,
    team_id: str,
    iterations: list[dict[str, Any]],
    selected_paths: set[str],
) -> int:
    rows = [
        (
            it["id"],
            None,  # iteration_sk is filled in once we observe it via Analytics data
            project_id,
            team_id,
            it["name"],
            it["path"],
            _date(it.get("attributes", {}).get("startDate")),
            _date(it.get("attributes", {}).get("finishDate")),
            it.get("attributes", {}).get("timeFrame"),
            it["path"] in selected_paths,
        )
        for it in iterations
    ]
    conn.executemany(
        """
        INSERT INTO iterations
            (iteration_id, iteration_sk, project_id, team_id, name, path,
             start_date, end_date, timeframe, is_selected)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (iteration_id) DO UPDATE SET
            name = excluded.name, path = excluded.path,
            start_date = excluded.start_date, end_date = excluded.end_date,
            timeframe = excluded.timeframe, is_selected = excluded.is_selected
        """,
        rows,
    )
    return len(rows)


def upsert_capacities(
    conn: duckdb.DuckDBPyConnection,
    iteration_id: str,
    team_id: str,
    capacities: dict[str, Any],
) -> int:
    conn.execute("DELETE FROM capacities WHERE iteration_id = ?", [iteration_id])
    conn.execute("DELETE FROM member_days_off WHERE iteration_id = ?", [iteration_id])

    capacity_rows = []
    days_off_rows = []
    for member in capacities.get("teamMembers", []):
        member_id = member["teamMember"]["id"]
        member_name = member["teamMember"].get("displayName")
        activities = member.get("activities") or [{"name": "", "capacityPerDay": 0}]
        for activity in activities:
            capacity_rows.append(
                (
                    iteration_id,
                    team_id,
                    member_id,
                    member_name,
                    activity.get("name") or "",
                    activity.get("capacityPerDay") or 0,
                )
            )
        for day_off in member.get("daysOff", []):
            days_off_rows.append(
                (iteration_id, member_id, _date(day_off["start"]), _date(day_off["end"]))
            )

    if capacity_rows:
        conn.executemany(
            """
            INSERT INTO capacities
                (iteration_id, team_id, team_member_id, member_name, activity,
                 capacity_per_day_hours)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (iteration_id, team_member_id, activity) DO UPDATE SET
                member_name = excluded.member_name,
                capacity_per_day_hours = excluded.capacity_per_day_hours
            """,
            capacity_rows,
        )
    if days_off_rows:
        conn.executemany(
            """
            INSERT INTO member_days_off (iteration_id, team_member_id, start_date, end_date)
            VALUES (?, ?, ?, ?)
            """,
            days_off_rows,
        )
    return len(capacity_rows)


def upsert_team_days_off(
    conn: duckdb.DuckDBPyConnection,
    iteration_id: str,
    team_id: str,
    team_days_off: dict[str, Any],
) -> int:
    conn.execute("DELETE FROM team_days_off WHERE iteration_id = ?", [iteration_id])
    rows = [
        (iteration_id, team_id, _date(d["start"]), _date(d["end"]))
        for d in team_days_off.get("daysOff", [])
    ]
    if rows:
        conn.executemany(
            "INSERT INTO team_days_off (iteration_id, team_id, start_date, end_date) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def upsert_work_items(
    conn: duckdb.DuckDBPyConnection,
    project_id: str,
    iteration_path: str,
    items: list[dict[str, Any]],
    states: StatesConfig,
) -> int:
    rows = []
    for wi in items:
        effort = wi.get("Effort")
        state = wi.get("State", "")
        state_category = wi.get("StateCategory", "")
        rows.append(
            (
                wi["WorkItemId"],
                project_id,
                wi.get("WorkItemType", ""),
                wi.get("Title"),
                state,
                state_category,
                classify_state(state, state_category, states),
                iteration_path,
                wi.get("IterationSK"),
                effort,
                _ts(wi.get("CreatedDate")),
                _ts(wi.get("ActivatedDate")),
                _ts(wi.get("ClosedDate")),
                _ts(wi.get("CompletedDate")),
                _ts(wi.get("ChangedDate")),
                wi.get("CycleTimeDays"),
                wi.get("LeadTimeDays"),
                wi.get("ParentWorkItemId"),
                wi.get("TagNames"),
            )
        )
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO work_items
            (work_item_id, project_id, work_item_type, title, state, state_category,
             effective_category, iteration_path, iteration_sk, effort, created_date,
             activated_date, closed_date, completed_date, changed_date,
             cycle_time_days, lead_time_days, parent_id, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (work_item_id) DO UPDATE SET
            work_item_type = excluded.work_item_type, title = excluded.title,
            state = excluded.state, state_category = excluded.state_category,
            effective_category = excluded.effective_category,
            iteration_path = excluded.iteration_path, iteration_sk = excluded.iteration_sk,
            effort = excluded.effort, created_date = excluded.created_date,
            activated_date = excluded.activated_date, closed_date = excluded.closed_date,
            completed_date = excluded.completed_date, changed_date = excluded.changed_date,
            cycle_time_days = excluded.cycle_time_days, lead_time_days = excluded.lead_time_days,
            parent_id = excluded.parent_id, tags = excluded.tags
        """,
        rows,
    )
    return len(rows)


def upsert_work_item_snapshots(
    conn: duckdb.DuckDBPyConnection,
    iteration_path: str,
    snapshots: list[dict[str, Any]],
    states: StatesConfig,
) -> int:
    rows = []
    for snap in snapshots:
        state = snap.get("State", "")
        state_category = snap.get("StateCategory", "")
        rows.append(
            (
                snap["WorkItemId"],
                _date(snap["DateValue"]),
                snap.get("WorkItemType", ""),
                state,
                state_category,
                classify_state(state, state_category, states),
                snap.get("Effort"),
                snap.get("RemainingWork"),
                snap.get("IterationSK"),
                iteration_path,
            )
        )
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO work_item_snapshots
            (work_item_id, snapshot_date, work_item_type, state, state_category,
             effective_category, effort, remaining_work, iteration_sk, iteration_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (work_item_id, snapshot_date) DO UPDATE SET
            work_item_type = excluded.work_item_type, state = excluded.state,
            state_category = excluded.state_category,
            effective_category = excluded.effective_category,
            effort = excluded.effort, remaining_work = excluded.remaining_work,
            iteration_sk = excluded.iteration_sk, iteration_path = excluded.iteration_path
        """,
        rows,
    )
    return len(rows)


def record_sync_log(
    conn: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    started_at: datetime,
    finished_at: datetime | None,
    source: str,
    entity: str,
    scope: str,
    watermark: str | None,
    row_count: int,
    status: str,
    error: str | None = None,
    raw_path: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO sync_log
            (run_id, started_at, finished_at, source, entity, scope, watermark,
             row_count, status, error, raw_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            run_id, started_at, finished_at, source, entity, scope, watermark,
            row_count, status, error, raw_path,
        ],
    )


def get_watermark(
    conn: duckdb.DuckDBPyConnection, source: str, entity: str, scope: str
) -> str | None:
    result = conn.execute(
        """
        SELECT watermark FROM sync_log
        WHERE source = ? AND entity = ? AND scope = ? AND status = 'ok' AND watermark IS NOT NULL
        ORDER BY finished_at DESC LIMIT 1
        """,
        [source, entity, scope],
    ).fetchone()
    return result[0] if result else None


def known_iterations(conn: duckdb.DuckDBPyConnection, team_id: str) -> list[IterationRecord]:
    rows = conn.execute(
        "SELECT path, iteration_id, start_date, end_date, timeframe FROM iterations "
        "WHERE team_id = ?",
        [team_id],
    ).fetchall()
    return [
        IterationRecord(
            path=r[0], iteration_id=r[1], start_date=r[2], end_date=r[3], timeframe=r[4]
        )
        for r in rows
    ]


def recent_sync_runs(conn: duckdb.DuckDBPyConnection, limit: int) -> list[tuple]:
    """Raw rows for `metrics status`; kept as tuples since the CLI just prints them."""
    return conn.execute(
        "SELECT run_id, entity, scope, status, row_count, finished_at FROM sync_log "
        "ORDER BY finished_at DESC NULLS LAST LIMIT ?",
        [limit],
    ).fetchall()


def local_iterations(conn: duckdb.DuckDBPyConnection, team_id: str) -> list[tuple]:
    """Raw rows for `metrics sprints list`; kept as tuples since the CLI just prints them."""
    return conn.execute(
        "SELECT path, timeframe, start_date, end_date, is_selected FROM iterations "
        "WHERE team_id = ? ORDER BY start_date",
        [team_id],
    ).fetchall()


class DuckDbSyncStore:
    """SyncStore port implementation — binds a connection and delegates to the
    module-level functions above, which remain independently usable/testable."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def upsert_project(self, project_id: str, organization: str) -> None:
        upsert_project(self._conn, project_id, organization)

    def upsert_team(self, team_id: str, project_id: str, name: str) -> None:
        upsert_team(self._conn, team_id, project_id, name)

    def upsert_iterations(
        self,
        project_id: str,
        team_id: str,
        iterations: list[dict[str, Any]],
        selected_paths: set[str],
    ) -> int:
        return upsert_iterations(self._conn, project_id, team_id, iterations, selected_paths)

    def upsert_capacities(
        self, iteration_id: str, team_id: str, capacities: dict[str, Any]
    ) -> int:
        return upsert_capacities(self._conn, iteration_id, team_id, capacities)

    def upsert_team_days_off(
        self, iteration_id: str, team_id: str, team_days_off: dict[str, Any]
    ) -> int:
        return upsert_team_days_off(self._conn, iteration_id, team_id, team_days_off)

    def upsert_work_items(
        self,
        project_id: str,
        iteration_path: str,
        items: list[dict[str, Any]],
        states: StatesConfig,
    ) -> int:
        return upsert_work_items(self._conn, project_id, iteration_path, items, states)

    def upsert_work_item_snapshots(
        self, iteration_path: str, snapshots: list[dict[str, Any]], states: StatesConfig
    ) -> int:
        return upsert_work_item_snapshots(self._conn, iteration_path, snapshots, states)

    def known_iterations(self, team_id: str) -> list[IterationRecord]:
        return known_iterations(self._conn, team_id)

    def record_sync_log(
        self,
        *,
        run_id: str,
        started_at: datetime,
        finished_at: datetime | None,
        source: str,
        entity: str,
        scope: str,
        watermark: str | None,
        row_count: int,
        status: str,
        error: str | None = None,
        raw_path: str | None = None,
    ) -> None:
        record_sync_log(
            self._conn,
            run_id=run_id, started_at=started_at, finished_at=finished_at, source=source,
            entity=entity, scope=scope, watermark=watermark, row_count=row_count,
            status=status, error=error, raw_path=raw_path,
        )

    def get_watermark(self, source: str, entity: str, scope: str) -> str | None:
        return get_watermark(self._conn, source, entity, scope)

    def recent_sync_runs(self, limit: int) -> list[tuple]:
        return recent_sync_runs(self._conn, limit)

    def local_iterations(self, team_id: str) -> list[tuple]:
        return local_iterations(self._conn, team_id)
