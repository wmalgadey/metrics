"""Steps for frozen_sprints.feature and incremental_sync.feature."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import respx
from pytest_bdd import given, parsers, scenarios, then, when

from metrics.azdo.http import make_client
from metrics.azdo.odata import ODataClient
from metrics.config import AzureDevOpsConfig
from metrics.sync.watermarks import is_frozen, parse_watermark_date, snapshot_date_range

scenarios("frozen_sprints.feature")
scenarios("incremental_sync.feature")

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "azdo"
CFG = AzureDevOpsConfig(organization="my-org", project="MyProject", team="MyTeam")


def _load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- frozen_sprints.feature ---------------------------------------------------


@given(parsers.parse('a sprint that ended on {end_date} with timeframe "{timeframe}"'))
def sprint_ended(bdd_context, end_date, timeframe):
    bdd_context["end_date"] = date.fromisoformat(end_date)
    bdd_context["timeframe"] = timeframe


@given(parsers.parse("a grace period of {days:d} days"))
def grace_period(bdd_context, days):
    bdd_context["grace_days"] = days


@given("a frozen sprint")
def a_frozen_sprint(bdd_context):
    bdd_context["end_date"] = date(2026, 1, 1)
    bdd_context["timeframe"] = "past"
    bdd_context["grace_days"] = 3


@when(parsers.parse("a sync runs on {today}"))
def sync_runs_on(bdd_context, today):
    today_date = date.fromisoformat(today)
    frozen = is_frozen(
        bdd_context["timeframe"], bdd_context["end_date"], today_date, bdd_context["grace_days"]
    )
    bdd_context["frozen"] = frozen
    bdd_context["synced"] = not frozen


@when("a sync runs with the full option")
def sync_runs_full(bdd_context):
    # --full bypasses the frozen check entirely: `if not full and is_frozen(...)`.
    bdd_context["synced"] = True


@then("the sprint is skipped as frozen")
def sprint_skipped(bdd_context):
    assert bdd_context["frozen"] is True
    assert bdd_context["synced"] is False


@then("the sprint is synced")
def sprint_is_synced(bdd_context):
    assert bdd_context["synced"] is True


# --- incremental_sync.feature --------------------------------------------------


@given(parsers.parse("a successful work-items sync recorded the watermark {watermark}"))
def recorded_watermark(bdd_context, watermark):
    bdd_context["watermark"] = watermark


@given("a successful work-items sync recorded a watermark")
def recorded_some_watermark(bdd_context):
    bdd_context["watermark"] = "2026-06-03T10:00:00Z"


@given(parsers.parse("a sprint from {start} to {end}"))
def sprint_from_to(bdd_context, start, end):
    bdd_context["sprint_start"] = date.fromisoformat(start)
    bdd_context["sprint_end"] = date.fromisoformat(end)


@given(parsers.parse("a snapshot watermark of {day}"))
def snapshot_watermark(bdd_context, day):
    bdd_context["snapshot_watermark"] = date.fromisoformat(day)


@when("an incremental sync runs")
def incremental_sync_runs(bdd_context):
    changed_since = parse_watermark_date(bdd_context["watermark"])
    with respx.mock:
        route = respx.get(f"{CFG.analytics_url}/WorkItems").mock(
            return_value=httpx.Response(200, json=_load_fixture("work_items_single_page.json"))
        )
        with make_client("fake-pat") as client:
            odata = ODataClient(client, CFG)
            list(odata.work_items("MyProject\\Sprint 23", changed_since))
        bdd_context["request_url"] = str(route.calls[0].request.url)


@when("an incremental sync runs with the full option")
def full_sync_ignores_watermark(bdd_context):
    with respx.mock:
        route = respx.get(f"{CFG.analytics_url}/WorkItems").mock(
            return_value=httpx.Response(200, json=_load_fixture("work_items_single_page.json"))
        )
        with make_client("fake-pat") as client:
            odata = ODataClient(client, CFG)
            list(odata.work_items("MyProject\\Sprint 23", None))  # full sync -> no changed_since
        bdd_context["request_url"] = str(route.calls[0].request.url)


@when(parsers.parse("the snapshot date range is computed on {today}"))
def compute_snapshot_range(bdd_context, today):
    today_date = date.fromisoformat(today)
    bdd_context["date_range"] = snapshot_date_range(
        bdd_context["sprint_start"],
        bdd_context["sprint_end"],
        bdd_context["snapshot_watermark"],
        today_date,
    )


def _decoded_filter(request_url: str) -> str:
    query = parse_qs(urlparse(request_url).query)
    return query.get("$filter", [""])[0]


@then(parsers.parse("the work tracking source is queried for changes since {day}"))
def queried_since(bdd_context, day):
    assert f"ChangedDate ge {day}" in _decoded_filter(bdd_context["request_url"])


@then("the work tracking source is queried without a change filter")
def queried_without_filter(bdd_context):
    assert "ChangedDate ge" not in _decoded_filter(bdd_context["request_url"])


@then(parsers.parse("snapshots are fetched from {start} through {end}"))
def snapshots_fetched_range(bdd_context, start, end):
    assert bdd_context["date_range"] == (date.fromisoformat(start), date.fromisoformat(end))
