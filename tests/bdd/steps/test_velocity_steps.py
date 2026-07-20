"""Steps for velocity_rolling_average.feature and cycle_time.feature."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from metrics.config import StatesConfig
from metrics.metrics.cycletime import cycle_time_percentiles
from metrics.metrics.velocity import sprint_velocity
from metrics.storage import loaders

scenarios("velocity_rolling_average.feature")
scenarios("cycle_time.feature")

TEAM_ID = "Proj/Team"
CYCLE_TIME_PATH = "Proj\\Sprint 1"


# --- velocity_rolling_average.feature ---------------------------------------


def _seed_velocity_sprint(conn, idx: int, start: date, end: date, completed: int) -> str:
    path = f"Proj\\Sprint {idx}"
    loaders.upsert_iterations(
        conn,
        "Proj",
        TEAM_ID,
        [
            {
                "id": f"it-{idx}",
                "name": f"Sprint {idx}",
                "path": path,
                "attributes": {
                    "startDate": f"{start.isoformat()}T00:00:00Z",
                    "finishDate": f"{end.isoformat()}T00:00:00Z",
                    "timeFrame": "past",
                },
            }
        ],
        {path},
    )
    snapshots = []
    for wi in range(1, completed + 1):
        work_item_id = idx * 100 + wi
        snapshots.append(
            {
                "WorkItemId": work_item_id, "DateValue": f"{start.isoformat()}T00:00:00Z",
                "WorkItemType": "Product Backlog Item", "State": "Committed",
                "StateCategory": "InProgress",
            }
        )
        snapshots.append(
            {
                "WorkItemId": work_item_id, "DateValue": f"{end.isoformat()}T00:00:00Z",
                "WorkItemType": "Product Backlog Item", "State": "Done",
                "StateCategory": "Completed",
            }
        )
    loaders.upsert_work_item_snapshots(conn, path, snapshots, StatesConfig())
    return path


@given(parsers.parse("three completed sprints with {a:d}, {b:d} and {c:d} completed items"))
def three_sprints(conn, bdd_context, a, b, c):
    loaders.upsert_project(conn, "Proj", "org")
    loaders.upsert_team(conn, TEAM_ID, "Proj", "Team")
    start = date(2026, 5, 1)
    paths = []
    for i, completed in enumerate([a, b, c], start=1):
        sprint_start = start + timedelta(days=(i - 1) * 14)
        sprint_end = sprint_start + timedelta(days=4)
        paths.append(_seed_velocity_sprint(conn, i, sprint_start, sprint_end, completed))
    bdd_context["paths"] = paths


@given(parsers.parse("one completed sprint with {n:d} completed items"))
def one_sprint(conn, bdd_context, n):
    loaders.upsert_project(conn, "Proj", "org")
    loaders.upsert_team(conn, TEAM_ID, "Proj", "Team")
    sprint_start = date(2026, 5, 1)
    sprint_end = sprint_start + timedelta(days=4)
    bdd_context["paths"] = [_seed_velocity_sprint(conn, 1, sprint_start, sprint_end, n)]


@given(parsers.parse("a rolling window of {n:d} sprints"))
def rolling_window(bdd_context, n):
    bdd_context["window"] = n


@when("the velocity is computed")
def compute_velocity(conn, bdd_context):
    bdd_context["velocity_points"] = sprint_velocity(
        conn, bdd_context["paths"], bdd_context["window"]
    )


@then(parsers.parse("the rolling average for the third sprint is {value:f}"))
def rolling_avg_third(bdd_context, value):
    assert bdd_context["velocity_points"][2].rolling_avg_items == pytest.approx(value)


@then(parsers.parse("the rolling average for that sprint is {value:f}"))
def rolling_avg_that(bdd_context, value):
    assert bdd_context["velocity_points"][0].rolling_avg_items == pytest.approx(value)


# --- cycle_time.feature ------------------------------------------------------


def _seed_completed_items(conn, cycle_times: list[int]) -> None:
    items = [
        {
            "WorkItemId": 1000 + i, "WorkItemType": "Product Backlog Item", "State": "Done",
            "StateCategory": "Completed", "CompletedDate": "2026-06-05T00:00:00Z",
            "CycleTimeDays": ct, "LeadTimeDays": ct + 1,
        }
        for i, ct in enumerate(cycle_times, start=1)
    ]
    loaders.upsert_work_items(conn, "Proj", CYCLE_TIME_PATH, items, StatesConfig())


def _seed_in_progress_item(conn) -> None:
    item = {
        "WorkItemId": 2000, "WorkItemType": "Product Backlog Item", "State": "Committed",
        "StateCategory": "InProgress", "CycleTimeDays": None, "LeadTimeDays": None,
    }
    loaders.upsert_work_items(conn, "Proj", CYCLE_TIME_PATH, [item], StatesConfig())


@given(
    parsers.parse("completed product backlog items with cycle times of {a:d}, {b:d} and {c:d} days")
)
def completed_items_cycle_times(conn, a, b, c):
    loaders.upsert_project(conn, "Proj", "org")
    _seed_completed_items(conn, [a, b, c])


@given(parsers.parse("{n:d} completed items with cycle times of {a:d} and {b:d} days"))
def n_completed_items(conn, n, a, b):
    assert n == 2
    loaders.upsert_project(conn, "Proj", "org")
    _seed_completed_items(conn, [a, b])


@given(parsers.parse("{n:d} item still in progress without a cycle time"))
def item_in_progress(conn, n):
    assert n == 1
    _seed_in_progress_item(conn)


@when("cycle time percentiles are computed")
def compute_cycle_time(conn, bdd_context):
    bdd_context["cycle_time_result"] = cycle_time_percentiles(conn)


@then(parsers.parse("the 50th percentile cycle time is {value:f} days"))
def p50_is(bdd_context, value):
    assert bdd_context["cycle_time_result"][0].cycle_time_p50 == pytest.approx(value)


@then(parsers.parse("the percentile population counts {n:d} items"))
def population_count(bdd_context, n):
    assert bdd_context["cycle_time_result"][0].count == n
