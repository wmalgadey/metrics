"""End-to-end: sync (mocked Azure DevOps) -> DuckDB -> export (mocked VictoriaMetrics),
driven through the actual CLI, exercising the full local pipeline."""

from __future__ import annotations

from pathlib import Path

import duckdb
import httpx
import respx
import yaml
from typer.testing import CliRunner

from metrics.cli import app
from metrics.config import AzureDevOpsConfig

runner = CliRunner()

CFG = AzureDevOpsConfig(organization="my-org", project="MyProject", team="MyTeam")
REST_BASE = f"{CFG.base_url}/MyProject/MyTeam/_apis/work/teamsettings"
ANALYTICS_BASE = CFG.analytics_url
ITERATION_ID = "11111111-1111-1111-1111-111111111111"
FIXTURES = Path(__file__).parent / "fixtures" / "azdo"


def _mock_azdo() -> None:
    import json

    def load(name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    respx.get(f"{REST_BASE}/iterations").mock(
        return_value=httpx.Response(200, json=load("iterations.json"))
    )
    respx.get(f"{REST_BASE}/iterations/{ITERATION_ID}/capacities").mock(
        return_value=httpx.Response(200, json=load("capacities.json"))
    )
    respx.get(f"{REST_BASE}/iterations/{ITERATION_ID}/teamdaysoff").mock(
        return_value=httpx.Response(200, json=load("teamdaysoff.json"))
    )
    respx.get(f"{ANALYTICS_BASE}/WorkItems").mock(
        return_value=httpx.Response(200, json=load("work_items_single_page.json"))
    )
    respx.get(f"{ANALYTICS_BASE}/WorkItemSnapshot").mock(
        return_value=httpx.Response(200, json=load("work_item_snapshots.json"))
    )


@respx.mock
def test_sync_then_export_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AZDO_PAT", "fake-pat")
    monkeypatch.setenv("COLUMNS", "200")  # avoid rich truncating table output
    _mock_azdo()

    config = {
        "azure_devops": {"organization": "my-org", "project": "MyProject", "team": "MyTeam"},
        "sprints": {"selected": ["MyProject\\Sprint 23"]},
        "paths": {"data_dir": "data"},
        # Sprint 23 in the fixtures ends 2026-06-14 — keep it unfrozen regardless
        # of the real wall-clock date the test happens to run on.
        "sync": {"closed_sprint_grace_days": 36500},
    }
    Path("config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    vm_route = respx.post("http://localhost:8428/api/v1/import/prometheus").mock(
        return_value=httpx.Response(204)
    )

    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert "ok" in result.output
    assert vm_route.called  # sync auto-exports afterwards

    # data actually landed in DuckDB
    conn = duckdb.connect(str(tmp_path / "data" / "metrics.duckdb"), read_only=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM work_item_snapshots").fetchone()[0] == 4
    finally:
        conn.close()

    # raw layer was written and is replayable
    raw_files = list((tmp_path / "data" / "raw" / "azdo").rglob("*.json.gz"))
    assert len(raw_files) >= 5

    # standalone `export` also works against the already-synced DB
    vm_route.calls.reset()
    export_result = runner.invoke(app, ["export"])
    assert export_result.exit_code == 0, export_result.output
    assert vm_route.called

    # the exported payload actually contains our metrics
    sent_bodies = b"".join(call.request.content for call in vm_route.calls)
    assert b"azdo_sprint_open_items" in sent_bodies
    assert b"azdo_cycle_time_days" in sent_bodies
    # cycle time is exported per sprint so dashboards can trend it
    cycle_lines = [
        line for line in sent_bodies.split(b"\n") if line.startswith(b"azdo_cycle_time_days")
    ]
    assert cycle_lines
    assert all(b'sprint="MyProject/Sprint 23"' in line for line in cycle_lines)


@respx.mock
def test_sprints_list_and_status_reflect_synced_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AZDO_PAT", "fake-pat")
    monkeypatch.setenv("COLUMNS", "200")  # avoid rich truncating table output
    _mock_azdo()
    respx.post("http://localhost:8428/api/v1/import/prometheus").mock(
        return_value=httpx.Response(204)
    )

    config = {
        "azure_devops": {"organization": "my-org", "project": "MyProject", "team": "MyTeam"},
        "sprints": {"selected": ["MyProject\\Sprint 23"]},
        "paths": {"data_dir": "data"},
        # Sprint 23 in the fixtures ends 2026-06-14 — keep it unfrozen regardless
        # of the real wall-clock date the test happens to run on.
        "sync": {"closed_sprint_grace_days": 36500},
    }
    Path("config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    assert runner.invoke(app, ["sync"]).exit_code == 0

    sprints_result = runner.invoke(app, ["sprints", "list"])
    assert sprints_result.exit_code == 0
    assert "Sprint 23" in sprints_result.output

    status_result = runner.invoke(app, ["status"])
    assert status_result.exit_code == 0
    assert "work_items" in status_result.output
