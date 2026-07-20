"""Steps for burndown_ideal_line.feature and scope_change.feature.

Bound directly against today's implementation in metrics.analytics.burndown
(private _working_days/_ideal_line included) — this pins the SQL-based
working-day/day-off semantics before Step 4 replaces it with a pure Python
calendar port. Re-point these imports when that lands.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from metrics.analytics.burndown import _ideal_line, _working_days, sprint_burndown
from metrics.storage import loaders

scenarios("burndown_ideal_line.feature")
scenarios("scope_change.feature")

ITERATION_ID = "it-1"
TEAM_ID = "Proj/Team"
PATH = "Proj\\Sprint 1"
SPRINT_DAYS = [date(2026, 6, 1) + timedelta(days=i) for i in range(5)]  # Mon-Fri


def _seed_iteration(conn, start: date, end: date) -> None:
    loaders.upsert_project(conn, "Proj", "org")
    loaders.upsert_team(conn, TEAM_ID, "Proj", "Team")
    loaders.upsert_iterations(
        conn,
        "Proj",
        TEAM_ID,
        [
            {
                "id": ITERATION_ID,
                "name": "Sprint",
                "path": PATH,
                "attributes": {
                    "startDate": f"{start.isoformat()}T00:00:00Z",
                    "finishDate": f"{end.isoformat()}T00:00:00Z",
                    "timeFrame": "past",
                },
            }
        ],
        {PATH},
    )


# --- burndown_ideal_line.feature -------------------------------------------


@given(
    parsers.re(
        r"a sprint from \w+ (?P<start>\d{4}-\d{2}-\d{2}) to \w+ "
        r"(?P<end>\d{4}-\d{2}-\d{2}) with no days off$"
    )
)
def sprint_with_no_days_off(conn, bdd_context, start, end):
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    _seed_iteration(conn, start_date, end_date)
    bdd_context["start"], bdd_context["end"] = start_date, end_date


@given(
    parsers.re(
        r"a sprint from \w+ (?P<start>\d{4}-\d{2}-\d{2}) to \w+ (?P<end>\d{4}-\d{2}-\d{2})$"
    )
)
def sprint_generic(conn, bdd_context, start, end):
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    _seed_iteration(conn, start_date, end_date)
    bdd_context["start"], bdd_context["end"] = start_date, end_date


@given(parsers.parse("a day-one scope of {scope:d} items"))
def day_one_scope(bdd_context, scope):
    bdd_context["day1_scope"] = scope


@given(parsers.parse("the whole team is off on {day}"))
def team_day_off(conn, day):
    off_date = date.fromisoformat(day)
    loaders.upsert_team_days_off(
        conn,
        ITERATION_ID,
        TEAM_ID,
        {
            "daysOff": [
                {
                    "start": f"{off_date.isoformat()}T00:00:00Z",
                    "end": f"{off_date.isoformat()}T00:00:00Z",
                }
            ]
        },
    )


@when("the ideal burndown line is computed")
def compute_ideal_line(conn, bdd_context):
    start, end = bdd_context["start"], bdd_context["end"]
    working_days = _working_days(conn, ITERATION_ID, start, end)
    bdd_context["ideal"] = _ideal_line(start, end, working_days, bdd_context["day1_scope"])


@then(parsers.parse("the ideal value on {day} is {value:f}"))
def ideal_value_is(bdd_context, day, value):
    assert bdd_context["ideal"][date.fromisoformat(day)] == pytest.approx(value)


@then(
    parsers.re(
        r"the ideal value on (?:\w+ )?(?P<day1>\d{4}-\d{2}-\d{2}) equals "
        r"the value on (?:\w+ )?(?P<day2>\d{4}-\d{2}-\d{2})"
    )
)
def ideal_value_equals(bdd_context, day1, day2):
    ideal = bdd_context["ideal"]
    assert ideal[date.fromisoformat(day1)] == ideal[date.fromisoformat(day2)]


# --- scope_change.feature ----------------------------------------------------


def _seed_daily_snapshots(
    conn, states, item_count, *, extra_item_from=None, removed_item=None, removed_on=None
):
    _seed_iteration(conn, SPRINT_DAYS[0], SPRINT_DAYS[-1])
    snapshots = []
    for day in SPRINT_DAYS:
        n = item_count + 1 if extra_item_from and day >= extra_item_from else item_count
        for wi in range(1, n + 1):
            state, category = "Committed", "InProgress"
            if removed_item == wi and removed_on and day >= removed_on:
                state, category = "Removed", "Removed"
            snapshots.append(
                {
                    "WorkItemId": wi,
                    "DateValue": f"{day.isoformat()}T00:00:00Z",
                    "WorkItemType": "Product Backlog Item",
                    "State": state,
                    "StateCategory": category,
                }
            )
    loaders.upsert_work_item_snapshots(conn, PATH, snapshots, states)


@given(
    parsers.parse("a synced sprint whose day-one snapshot contains {n:d} product backlog items")
)
def synced_sprint_day1(states, bdd_context, n):
    bdd_context.update(
        states=states, item_count=n, extra_item_from=None, removed_item=None, removed_on=None
    )


@given(parsers.parse("a fourth item appears in the daily snapshots from {day} on"))
def fourth_item_from(bdd_context, day):
    bdd_context["extra_item_from"] = date.fromisoformat(day)


@given(parsers.parse("a synced sprint with {n:d} items open on day one"))
def synced_sprint_open(states, bdd_context, n):
    bdd_context.update(
        states=states, item_count=n, extra_item_from=None, removed_item=None, removed_on=None
    )


@given(parsers.parse('item {item:d} is moved to state "{state}" in the snapshot of {day}'))
def item_moved_to_state(bdd_context, item, state, day):
    assert state == "Removed"
    bdd_context["removed_item"] = item
    bdd_context["removed_on"] = date.fromisoformat(day)


@when("the burndown is computed")
def compute_burndown(conn, bdd_context):
    _seed_daily_snapshots(
        conn,
        bdd_context["states"],
        bdd_context["item_count"],
        extra_item_from=bdd_context.get("extra_item_from"),
        removed_item=bdd_context.get("removed_item"),
        removed_on=bdd_context.get("removed_on"),
    )
    points = sprint_burndown(conn, PATH)
    bdd_context["points_by_day"] = {p.day: p for p in points}


@then(parsers.parse("the scope on {day} is {n:d} items"))
def scope_on_day_is(bdd_context, day, n):
    assert bdd_context["points_by_day"][date.fromisoformat(day)].scope_items == n


@then(parsers.parse("the open items on {day} are {n:d}"))
def open_items_on_day_is(bdd_context, day, n):
    assert bdd_context["points_by_day"][date.fromisoformat(day)].open_items == n
