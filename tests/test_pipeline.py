from datetime import date
from pathlib import Path

import duckdb
import httpx
import respx

from metrics.config import (
    AppConfig,
    AzureDevOpsConfig,
    MetricsConfig,
    PathsConfig,
    SprintsConfig,
    SyncConfig,
)
from metrics.storage.db import apply_schema
from metrics.sync.pipeline import run_sync

CFG = AzureDevOpsConfig(organization="my-org", project="MyProject", team="MyTeam")
REST_BASE = f"{CFG.base_url}/MyProject/MyTeam/_apis/work/teamsettings"
ANALYTICS_BASE = CFG.analytics_url
ITERATION_ID = "11111111-1111-1111-1111-111111111111"


def _mock_azdo(load_fixture):
    respx.get(f"{REST_BASE}/iterations").mock(
        return_value=httpx.Response(200, json=load_fixture("iterations.json"))
    )
    respx.get(f"{REST_BASE}/iterations/{ITERATION_ID}/capacities").mock(
        return_value=httpx.Response(200, json=load_fixture("capacities.json"))
    )
    respx.get(f"{REST_BASE}/iterations/{ITERATION_ID}/teamdaysoff").mock(
        return_value=httpx.Response(200, json=load_fixture("teamdaysoff.json"))
    )
    respx.get(f"{ANALYTICS_BASE}/WorkItems").mock(
        return_value=httpx.Response(200, json=load_fixture("work_items_single_page.json"))
    )
    respx.get(f"{ANALYTICS_BASE}/WorkItemSnapshot").mock(
        return_value=httpx.Response(200, json=load_fixture("work_item_snapshots.json"))
    )


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        azure_devops=CFG,
        sprints=SprintsConfig(selected=["MyProject\\Sprint 23"]),
        metrics=MetricsConfig(),
        sync=SyncConfig(closed_sprint_grace_days=3),
        paths=PathsConfig(data_dir=str(tmp_path)),
    )


@respx.mock
def test_run_sync_populates_db(tmp_path, load_fixture):
    _mock_azdo(load_fixture)
    config = _config(tmp_path)
    conn = duckdb.connect(":memory:")
    apply_schema(conn)

    results = run_sync(config, "fake-pat", conn, today=date(2026, 6, 15))

    statuses = {(r.entity, r.scope): r.status for r in results}
    assert statuses[("iterations", "global")] == "ok"
    assert statuses[("work_items", "MyProject\\Sprint 23")] == "ok"
    assert statuses[("work_item_snapshots", "MyProject\\Sprint 23")] == "ok"

    work_items = conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0]
    assert work_items == 2
    snapshots = conn.execute("SELECT COUNT(*) FROM work_item_snapshots").fetchone()[0]
    assert snapshots == 4
    capacities = conn.execute("SELECT COUNT(*) FROM capacities").fetchone()[0]
    assert capacities == 2

    # raw layer was written
    raw_files = list((tmp_path / "raw" / "azdo").rglob("*.json.gz"))
    assert len(raw_files) >= 5

    # sync_log has one 'ok' row per entity
    log_rows = conn.execute("SELECT COUNT(*) FROM sync_log WHERE status = 'ok'").fetchone()[0]
    assert log_rows == 5  # iterations, capacities, team_days_off, work_items, snapshots


@respx.mock
def test_run_sync_skips_frozen_sprint(tmp_path, load_fixture):
    _mock_azdo(load_fixture)
    config = _config(tmp_path)
    conn = duckdb.connect(":memory:")
    apply_schema(conn)

    # Far beyond the grace period after Sprint 23's end date (2026-06-14)
    results = run_sync(config, "fake-pat", conn, today=date(2026, 8, 1))

    statuses = {(r.entity, r.scope): r.status for r in results}
    assert statuses[("work_items", "MyProject\\Sprint 23")] == "skipped-frozen"
    assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0


@respx.mock
def test_run_sync_unknown_sprint_reported_as_error(tmp_path, load_fixture):
    _mock_azdo(load_fixture)
    config = _config(tmp_path)
    conn = duckdb.connect(":memory:")
    apply_schema(conn)

    results = run_sync(
        config, "fake-pat", conn, sprints=["MyProject\\Nonexistent"], today=date(2026, 6, 15)
    )

    errors = [r for r in results if r.status == "error"]
    assert any("Nonexistent" in (r.error or "") for r in errors)
