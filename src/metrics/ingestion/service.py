"""Sync use case: fetch from a WorkTrackingSource -> RawArchive -> SyncStore,
per sprint. Depends only on the ports — the CLI composition root builds the
concrete adapters (see cli.py) and calls sync_sprints() directly."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from uuid import uuid4

from ..config import AppConfig
from .domain.model import SyncResult
from .domain.watermarks import is_frozen, parse_watermark_date, snapshot_date_range
from .ports import RawArchive, SyncStore, WorkTrackingSource

log = logging.getLogger(__name__)

SOURCE = "azdo"


def new_run_id() -> str:
    return f"{datetime.now(tz=UTC):%Y%m%dT%H%M%S}-{uuid4().hex[:6]}"


def _team_id(config: AppConfig) -> str:
    return f"{config.azure_devops.project}/{config.azure_devops.team}"


def _log_and_collect(
    store: SyncStore,
    results: list[SyncResult],
    *,
    run_id: str,
    entity: str,
    scope: str,
    fn,
) -> None:
    started = datetime.now(tz=UTC)
    log.info("syncing %s/%s...", entity, scope)
    try:
        row_count, watermark, raw_path = fn()
        log.info("synced %s/%s: %d row(s)", entity, scope, row_count)
        store.record_sync_log(
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
        store.record_sync_log(
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


def sync_sprints(
    source: WorkTrackingSource,
    store: SyncStore,
    archive: RawArchive,
    config: AppConfig,
    *,
    sprints: list[str] | None = None,
    full: bool = False,
    today: date | None = None,
) -> list[SyncResult]:
    today = today or datetime.now(tz=UTC).date()
    run_id = new_run_id()
    results: list[SyncResult] = []

    team_id = _team_id(config)
    store.upsert_project(config.azure_devops.project, config.azure_devops.organization)
    store.upsert_team(team_id, config.azure_devops.project, config.azure_devops.team)

    selected_paths = set(config.sprints.selected)
    target_paths = set(sprints) if sprints else selected_paths

    def _fetch_iterations():
        all_iterations = source.list_iterations()
        raw_path = archive.write(SOURCE, "iterations", run_id, "global", all_iterations)
        row_count = store.upsert_iterations(
            config.azure_devops.project, team_id, all_iterations, selected_paths
        )
        return row_count, None, raw_path

    _log_and_collect(
        store, results, run_id=run_id, entity="iterations", scope="global", fn=_fetch_iterations
    )
    if results[-1].status == "error":
        return results  # can't proceed without iteration metadata

    known = {record.path: record for record in store.known_iterations(team_id)}

    sorted_paths = sorted(target_paths)
    log.info("syncing %d sprint(s)", len(sorted_paths))
    for i, path in enumerate(sorted_paths, start=1):
        record = known.get(path)
        if record is None:
            log.error("'%s' is not a known iteration for team '%s'", path, team_id)
            results.append(
                SyncResult(
                    "work_items", path, 0, "error",
                    f"'{path}' is not a known iteration for team '{team_id}' "
                    "(check config.yaml sprints.selected)",
                )
            )
            continue

        if not full and is_frozen(
            record.timeframe, record.end_date, today, config.sync.closed_sprint_grace_days
        ):
            log.info("[%d/%d] %s: skipped (frozen)", i, len(sorted_paths), path)
            results.append(SyncResult("work_items", path, 0, "skipped-frozen"))
            continue

        log.info("[%d/%d] %s", i, len(sorted_paths), path)
        _sync_sprint(
            source, store, archive, config, run_id, path, record.iteration_id,
            record.start_date, record.end_date, team_id, full, today, results,
        )

    return results


def _sync_sprint(
    source: WorkTrackingSource,
    store: SyncStore,
    archive: RawArchive,
    config: AppConfig,
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
        capacities = source.get_capacities(iteration_id)
        raw_path = archive.write(SOURCE, "capacities", run_id, path, [capacities])
        row_count = store.upsert_capacities(iteration_id, team_id, capacities)
        return row_count, None, raw_path

    _log_and_collect(
        store, results, run_id=run_id, entity="capacities", scope=path, fn=_fetch_capacities
    )

    def _fetch_days_off():
        days_off = source.get_team_days_off(iteration_id)
        raw_path = archive.write(SOURCE, "team_days_off", run_id, path, [days_off])
        row_count = store.upsert_team_days_off(iteration_id, team_id, days_off)
        return row_count, None, raw_path

    _log_and_collect(
        store, results, run_id=run_id, entity="team_days_off", scope=path, fn=_fetch_days_off
    )

    def _fetch_work_items():
        watermark = None if full else store.get_watermark(SOURCE, "work_items", path)
        changed_since = parse_watermark_date(watermark)
        items = list(source.work_items(path, changed_since))
        raw_path = archive.write(SOURCE, "work_items", run_id, path, items)
        row_count = store.upsert_work_items(config.azure_devops.project, path, items, states)
        new_watermark = max(
            (i.get("ChangedDate") for i in items if i.get("ChangedDate")), default=watermark
        )
        return row_count, new_watermark, raw_path

    _log_and_collect(
        store, results, run_id=run_id, entity="work_items", scope=path, fn=_fetch_work_items
    )

    def _fetch_snapshots():
        watermark = None if full else store.get_watermark(SOURCE, "work_item_snapshots", path)
        watermark_date = parse_watermark_date(watermark)
        sprint_start = start_date or today
        sprint_end = end_date or today
        date_from, date_to = snapshot_date_range(sprint_start, sprint_end, watermark_date, today)
        snapshots = list(source.work_item_snapshots(path, date_from, date_to))
        raw_path = archive.write(SOURCE, "work_item_snapshots", run_id, path, snapshots)
        row_count = store.upsert_work_item_snapshots(path, snapshots, states)
        new_watermark = max(
            (s.get("DateValue") for s in snapshots if s.get("DateValue")), default=watermark
        )
        return row_count, new_watermark, raw_path

    _log_and_collect(
        store, results, run_id=run_id, entity="work_item_snapshots", scope=path,
        fn=_fetch_snapshots,
    )
