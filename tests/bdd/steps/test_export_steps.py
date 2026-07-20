"""Steps for idempotent_export.feature."""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import respx
from pytest_bdd import given, parsers, scenarios, then, when

from metrics.analytics.adapters.duckdb_repository import DuckDbSprintMetricsRepository
from metrics.ingestion.adapters import duckdb_store as loaders
from metrics.publishing.adapters.victoriametrics import VictoriaMetricsSink
from metrics.publishing.service import publish_metrics

scenarios("idempotent_export.feature")

TEAM_ID = "Proj/Team"
PATH = "Proj\\Sprint 1"
VM_URL = "http://vm.local:8428"


def _seed_synced_sprint(conn, states) -> None:
    loaders.upsert_project(conn, "Proj", "org")
    loaders.upsert_team(conn, TEAM_ID, "Proj", "Team")
    loaders.upsert_iterations(
        conn,
        "Proj",
        TEAM_ID,
        [
            {
                "id": "it-1", "name": "Sprint 1", "path": PATH,
                "attributes": {
                    "startDate": "2026-06-01T00:00:00Z", "finishDate": "2026-06-05T00:00:00Z",
                    "timeFrame": "past",
                },
            }
        ],
        {PATH},
    )
    snapshots = [
        {
            "WorkItemId": 1, "DateValue": "2026-06-01T00:00:00Z", "WorkItemType": "Bug",
            "State": "Committed", "StateCategory": "InProgress",
        }
    ]
    loaders.upsert_work_item_snapshots(conn, PATH, snapshots, states)


@given("a synced sprint in the local store")
def synced_sprint(conn, states):
    _seed_synced_sprint(conn, states)


@given(parsers.parse("a synced sprint with snapshots for {day}"))
def synced_sprint_with_day(conn, states, bdd_context, day):
    _seed_synced_sprint(conn, states)
    bdd_context["snapshot_day"] = date.fromisoformat(day)


@when("the metrics are exported twice")
def export_twice(conn, bdd_context):
    repo = DuckDbSprintMetricsRepository(conn)
    sink = VictoriaMetricsSink(VM_URL)
    with respx.mock:
        route = respx.post(f"{VM_URL}/api/v1/import/prometheus").mock(
            return_value=httpx.Response(204)
        )
        for _ in range(2):
            publish_metrics(
                repo, sink, project="Proj", team="Team", iteration_paths=[PATH],
                rolling_window=3,
            )
        bdd_context["push_bodies"] = [call.request.content for call in route.calls]


@when("the metrics are exported")
def export_once(conn, bdd_context):
    repo = DuckDbSprintMetricsRepository(conn)
    sink = VictoriaMetricsSink(VM_URL)
    with respx.mock:
        route = respx.post(f"{VM_URL}/api/v1/import/prometheus").mock(
            return_value=httpx.Response(204)
        )
        publish_metrics(
            repo, sink, project="Proj", team="Team", iteration_paths=[PATH],
            rolling_window=3,
        )
        bdd_context["push_body"] = route.calls[0].request.content


@then("both pushes contain exactly the same sample lines")
def same_lines(bdd_context):
    bodies = bdd_context["push_bodies"]
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]
    assert bodies[0]  # not empty — actually exercised the export


@then(
    parsers.parse("every burndown sample for {day} has the timestamp of that day at midnight UTC")
)
def timestamp_is_midnight(bdd_context, day):
    d = date.fromisoformat(day)
    expected_ts = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)
    body = bdd_context["push_body"].decode()
    # Only one sprint is seeded in this scenario, so no need to filter by label.
    burndown_lines = [
        line
        for line in body.splitlines()
        if line.startswith(("azdo_sprint_open_items", "azdo_sprint_scope_items"))
    ]
    assert burndown_lines, "expected at least one burndown sample line"
    for line in burndown_lines:
        ts = int(line.rsplit(" ", 1)[-1])
        assert ts == expected_ts
