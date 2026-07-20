"""Sync orchestration: fetch from Azure DevOps -> raw layer -> DuckDB, per sprint."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

import duckdb

from ..azdo.http import make_client
from ..azdo.odata import ODataClient
from ..azdo.rest import RestClient
from ..config import AppConfig
from ..storage import loaders, raw
from .watermarks import is_frozen, parse_watermark_date, snapshot_date_range

log = logging.getLogger(__name__)

SOURCE = "azdo"


@dataclass
class SyncResult:
    entity: str
    scope: str
    row_count: int
    status: str
    error: str | None = None


def new_run_id() -> str:
    return f"{datetime.now(tz=UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:6]}"


def _team_id(config: AppConfig) -> str:
    return f"{config.azure_devops.project}/{config.azure_devops.team}"


def _log_and_collect(
    conn: duckdb.DuckDBPyConnection,
    results: list[SyncResult],
    *,
    run_id: str,
    entity: str,
    scope: str,
    fn,
) -> None:
    started = datetime.now(tz=UTC)
    try:
        row_count, watermark, raw_path = fn()
        loaders.record_sync_log(
            conn,
            run_id=run_id,
            started_at=started,
            finished_at=datetime.now(tz=UTC),
            source=SOURCE,
            entity=entity,
            scope=scope,
            watermark=watermark,
            row_count=row_count,
            status="ok",
            raw_path=str(raw_path) if raw_path else None,
        )
        results.append(SyncResult(entity, scope, row_count, "ok"))
    except Exception as exc:  # noqa: BLE001 — recorded and re-raised to the caller's summary
        loaders.record_sync_log(
            conn,
            run_id=run_id,
            started_at=started,
            finished_at=datetime.now(tz=UTC),
            source=SOURCE,
            entity=entity,
            scope=scope,
            watermark=None,
            row_count=0,
            status="error",
            error=str(exc),
        )
        results.append(SyncResult(entity, scope, 0, "error", str(exc)))
        log.error("sync failed: entity=%s scope=%s: %s", entity, scope, exc)


def run_sync(
    config: AppConfig,
    pat: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    sprints: list[str] | None = None,
    full: bool = False,
    today: date | None = None,
) -> list[SyncResult]:
    today = today or datetime.now(tz=UTC).date()
    run_id = new_run_id()
    results: list[SyncResult] = []

    team_id = _team_id(config)
    loaders.upsert_project(conn, config.azure_devops.project, config.azure_devops.organization)
    loaders.upsert_team(conn, team_id, config.azure_devops.project, config.azure_devops.team)

    with make_client(pat) as client:
        rest = RestClient(client, config.azure_devops)
        odata = ODataClient(client, config.azure_devops)

        selected_paths = set(config.sprints.selected)
        target_paths = set(sprints) if sprints else selected_paths

        def _fetch_iterations():
            all_iterations = rest.list_iterations()
            raw_path = raw.write_raw(
                config.data_dir, SOURCE, "iterations", run_id, "global", all_iterations
            )
            row_count = loaders.upsert_iterations(
                conn, config.azure_devops.project, team_id, all_iterations, selected_paths
            )
            return row_count, None, raw_path

        _log_and_collect(
            conn, results, run_id=run_id, entity="iterations", scope="global", fn=_fetch_iterations
        )
        if results[-1].status == "error":
            return results  # can't proceed without iteration metadata

        known = {
            row[0]: row
            for row in conn.execute(
                "SELECT path, iteration_id, start_date, end_date, timeframe FROM iterations "
                "WHERE team_id = ?",
                [team_id],
            ).fetchall()
        }

        for path in sorted(target_paths):
            iteration = known.get(path)
            if iteration is None:
                results.append(
                    SyncResult(
                        "work_items", path, 0, "error",
                        f"'{path}' is not a known iteration for team '{team_id}' "
                        "(check config.yaml sprints.selected)",
                    )
                )
                continue
            _, iteration_id, start_date, end_date, timeframe = iteration

            if not full and is_frozen(
                timeframe, end_date, today, config.sync.closed_sprint_grace_days
            ):
                results.append(SyncResult("work_items", path, 0, "skipped-frozen"))
                continue

            _sync_sprint(
                config, conn, rest, odata, run_id, path, iteration_id,
                start_date, end_date, team_id, full, today, results,
            )

    return results


def _sync_sprint(
    config: AppConfig,
    conn: duckdb.DuckDBPyConnection,
    rest: RestClient,
    odata: ODataClient,
    run_id: str,
    path: str,
    iteration_id: str,
    start_date: date | None,
    end_date: date | None,
    team_id: str,
    full: bool,
    today: date,
    results: list[SyncResult],
) -> None:
    states = config.metrics.states

    def _fetch_capacities():
        capacities = rest.get_capacities(iteration_id)
        raw_path = raw.write_raw(
            config.data_dir, SOURCE, "capacities", run_id, path, [capacities]
        )
        row_count = loaders.upsert_capacities(conn, iteration_id, team_id, capacities)
        return row_count, None, raw_path

    _log_and_collect(
        conn, results, run_id=run_id, entity="capacities", scope=path, fn=_fetch_capacities
    )

    def _fetch_days_off():
        days_off = rest.get_team_days_off(iteration_id)
        raw_path = raw.write_raw(
            config.data_dir, SOURCE, "team_days_off", run_id, path, [days_off]
        )
        row_count = loaders.upsert_team_days_off(conn, iteration_id, team_id, days_off)
        return row_count, None, raw_path

    _log_and_collect(
        conn, results, run_id=run_id, entity="team_days_off", scope=path, fn=_fetch_days_off
    )

    def _fetch_work_items():
        watermark = None if full else loaders.get_watermark(conn, SOURCE, "work_items", path)
        changed_since = parse_watermark_date(watermark)
        items = list(odata.work_items(path, changed_since))
        raw_path = raw.write_raw(config.data_dir, SOURCE, "work_items", run_id, path, items)
        row_count = loaders.upsert_work_items(
            conn, config.azure_devops.project, path, items, states
        )
        new_watermark = max(
            (i.get("ChangedDate") for i in items if i.get("ChangedDate")), default=watermark
        )
        return row_count, new_watermark, raw_path

    _log_and_collect(
        conn, results, run_id=run_id, entity="work_items", scope=path, fn=_fetch_work_items
    )

    def _fetch_snapshots():
        watermark = None if full else loaders.get_watermark(
            conn, SOURCE, "work_item_snapshots", path
        )
        watermark_date = parse_watermark_date(watermark)
        sprint_start = start_date or today
        sprint_end = end_date or today
        date_from, date_to = snapshot_date_range(sprint_start, sprint_end, watermark_date, today)
        snapshots = list(odata.work_item_snapshots(path, date_from, date_to))
        raw_path = raw.write_raw(
            config.data_dir, SOURCE, "work_item_snapshots", run_id, path, snapshots
        )
        row_count = loaders.upsert_work_item_snapshots(conn, path, snapshots, states)
        new_watermark = max(
            (s.get("DateValue") for s in snapshots if s.get("DateValue")), default=watermark
        )
        return row_count, new_watermark, raw_path

    _log_and_collect(
        conn, results, run_id=run_id, entity="work_item_snapshots", scope=path, fn=_fetch_snapshots
    )
