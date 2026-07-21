from datetime import date

import duckdb
import pytest

from metrics.analytics import service as analytics_service
from metrics.analytics.adapters.duckdb_repository import DuckDbSprintMetricsRepository
from metrics.config import StatesConfig
from metrics.ingestion.adapters import duckdb_store as loaders
from metrics.shared.duckdb.db import apply_schema

STATES = StatesConfig(done=["Done"], in_progress=["Committed"], removed=["Removed"])


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    apply_schema(c)
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return DuckDbSprintMetricsRepository(conn)


def _seed_sprint(conn, path="Proj\\Sprint 1", start="2026-06-01", end="2026-06-05"):
    """Mon 2026-06-01 .. Fri 2026-06-05, a 5-working-day sprint, no days off."""
    loaders.upsert_project(conn, "Proj", "org")
    loaders.upsert_team(conn, "Proj/Team", "Proj", "Team")
    loaders.upsert_iterations(
        conn, "Proj", "Proj/Team",
        [
            {
                "id": "it-1", "name": "Sprint 1", "path": path,
                "attributes": {
                    "startDate": f"{start}T00:00:00Z", "finishDate": f"{end}T00:00:00Z",
                    "timeFrame": "past",
                },
            }
        ],
        {path},
    )
    return path


def test_burndown_ideal_line_decreases_linearly_to_zero(conn, repo):
    path = _seed_sprint(conn)
    # 4 PBIs open on day 1, all still open through day 5 (worst case: no progress)
    snapshots = []
    for day in ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]:
        for wi in range(1, 5):
            snapshots.append(
                {
                    "WorkItemId": wi, "DateValue": f"{day}T00:00:00Z",
                    "WorkItemType": "Product Backlog Item", "State": "Committed",
                    "StateCategory": "InProgress",
                }
            )
    loaders.upsert_work_item_snapshots(conn, path, snapshots, STATES)

    points = analytics_service.sprint_burndown(repo, path)
    by_day = {p.day: p for p in points}

    assert by_day[date(2026, 6, 1)].ideal_open_items == pytest.approx(4.0)
    assert by_day[date(2026, 6, 5)].ideal_open_items == pytest.approx(0.0)
    # linear: day 3 (index 2 of 5) -> 4 * (1 - 2/4) = 2.0
    assert by_day[date(2026, 6, 3)].ideal_open_items == pytest.approx(2.0)
    # actual open items never drop (no items completed in this fixture)
    assert by_day[date(2026, 6, 5)].open_items == 4


def test_burndown_ideal_line_flat_over_weekend(conn, repo):
    # Sprint spans a weekend: Fri 2026-06-05 .. Mon 2026-06-08 (2 working days: Fri, Mon)
    _seed_sprint(conn, path="Proj\\Sprint 2", start="2026-06-05", end="2026-06-08")
    snapshots = [
        {
            "WorkItemId": 1, "DateValue": f"{d}T00:00:00Z", "WorkItemType": "Bug",
            "State": "Committed", "StateCategory": "InProgress",
        }
        for d in ["2026-06-05", "2026-06-06", "2026-06-07", "2026-06-08"]
    ]
    loaders.upsert_work_item_snapshots(conn, "Proj\\Sprint 2", snapshots, STATES)

    points = analytics_service.sprint_burndown(repo, "Proj\\Sprint 2")
    by_day = {p.day: p for p in points}
    # day1 (Fri) ideal = 1.0, last working day (Mon) ideal = 0.0
    assert by_day[date(2026, 6, 5)].ideal_open_items == pytest.approx(1.0)
    assert by_day[date(2026, 6, 8)].ideal_open_items == pytest.approx(0.0)
    # Saturday/Sunday carry the last working-day value (Friday's 1.0) flat
    assert by_day[date(2026, 6, 6)].ideal_open_items == pytest.approx(1.0)
    assert by_day[date(2026, 6, 7)].ideal_open_items == pytest.approx(1.0)


def test_burndown_excludes_removed_items_from_scope(conn, repo):
    path = _seed_sprint(conn)
    snapshots = [
        {
            "WorkItemId": 1, "DateValue": "2026-06-01T00:00:00Z", "WorkItemType": "Bug",
            "State": "Removed", "StateCategory": "Removed",
        },
    ]
    loaders.upsert_work_item_snapshots(conn, path, snapshots, STATES)
    points = analytics_service.sprint_burndown(repo, path)
    assert points[0].scope_items == 0
    assert points[0].open_items == 0


def test_velocity_planned_vs_completed_and_rolling_average(conn, repo):
    # Two sprints, sequential; each has 4 planned PBIs, sprint1 completes 2, sprint2 completes 4.
    loaders.upsert_project(conn, "Proj", "org")
    loaders.upsert_team(conn, "Proj/Team", "Proj", "Team")
    for i, (path, start, end, completed) in enumerate(
        [
            ("Proj\\Sprint A", "2026-06-01", "2026-06-05", 2),
            ("Proj\\Sprint B", "2026-06-08", "2026-06-12", 4),
        ]
    ):
        loaders.upsert_iterations(
            conn, "Proj", "Proj/Team",
            [
                {
                    "id": f"it-{i}", "name": path, "path": path,
                    "attributes": {
                        "startDate": f"{start}T00:00:00Z", "finishDate": f"{end}T00:00:00Z",
                        "timeFrame": "past",
                    },
                }
            ],
            {path},
        )
        snapshots = []
        for wi in range(1, 5):
            state, cat = ("Done", "Completed") if wi <= completed else ("Committed", "InProgress")
            snapshots.append(
                {
                    "WorkItemId": i * 10 + wi, "DateValue": f"{start}T00:00:00Z",
                    "WorkItemType": "Product Backlog Item", "State": "Committed",
                    "StateCategory": "InProgress",
                }
            )
            snapshots.append(
                {
                    "WorkItemId": i * 10 + wi, "DateValue": f"{end}T00:00:00Z",
                    "WorkItemType": "Product Backlog Item", "State": state, "StateCategory": cat,
                }
            )
        loaders.upsert_work_item_snapshots(conn, path, snapshots, STATES)

    points = analytics_service.sprint_velocity(
        repo, ["Proj\\Sprint A", "Proj\\Sprint B"], rolling_window=2
    )
    assert [p.completed_items for p in points] == [2, 4]
    assert points[0].planned_items == 4
    # rolling avg over window=2: sprint A alone -> 2.0; A+B -> (2+4)/2 = 3.0
    assert points[0].rolling_avg_items == pytest.approx(2.0)
    assert points[1].rolling_avg_items == pytest.approx(3.0)


def test_capacity_vs_velocity_normalizes_by_hours(conn, repo):
    path = _seed_sprint(conn)
    loaders.upsert_capacities(
        conn, "it-1", "Proj/Team",
        {
            "teamMembers": [
                {
                    "teamMember": {"id": "u1", "displayName": "Alice"},
                    "activities": [{"name": "Dev", "capacityPerDay": 1}],
                    "daysOff": [],
                }
            ]
        },
    )
    snapshots = [
        {
            "WorkItemId": 1, "DateValue": "2026-06-01T00:00:00Z", "WorkItemType": "Bug",
            "State": "Committed", "StateCategory": "InProgress",
        },
        {
            "WorkItemId": 1, "DateValue": "2026-06-05T00:00:00Z", "WorkItemType": "Bug",
            "State": "Done", "StateCategory": "Completed",
        },
    ]
    loaders.upsert_work_item_snapshots(conn, path, snapshots, STATES)

    points = analytics_service.capacity_vs_velocity(repo, [path])
    assert len(points) == 1
    # 5 working days * 6h = 30h capacity; 1 completed item -> 1/30
    assert points[0].capacity_hours == pytest.approx(30.0)
    assert points[0].completed_items == 1
    assert points[0].items_per_capacity_hour == pytest.approx(1 / 30)


def test_capacity_daily_remaining_line_decreases_by_daily_hours(conn, repo):
    path = _seed_sprint(conn)  # Mon 2026-06-01 .. Fri 2026-06-05
    loaders.upsert_capacities(
        conn, "it-1", "Proj/Team",
        {
            "teamMembers": [
                {
                    "teamMember": {"id": "u1", "displayName": "Alice"},
                    "activities": [{"name": "Dev", "capacityPerDay": 1}],
                    "daysOff": [],
                }
            ]
        },
    )

    points = analytics_service.sprint_capacity_daily(repo, path)
    by_day = {p.day: p for p in points}

    assert len(points) == 5
    # 6h/day; remaining on a day includes that day through the sprint end
    assert by_day[date(2026, 6, 1)].capacity_hours == pytest.approx(6.0)
    assert by_day[date(2026, 6, 1)].remaining_capacity_hours == pytest.approx(30.0)
    assert by_day[date(2026, 6, 3)].remaining_capacity_hours == pytest.approx(18.0)
    assert by_day[date(2026, 6, 5)].remaining_capacity_hours == pytest.approx(6.0)


def test_capacity_daily_flat_over_weekend_and_days_off(conn, repo):
    # Fri 2026-06-05 .. Tue 2026-06-09: working days Fri, Mon, Tue; Monday is a
    # member day off, so it contributes 0 hours.
    path = _seed_sprint(conn, path="Proj\\Sprint W", start="2026-06-05", end="2026-06-09")
    loaders.upsert_capacities(
        conn, "it-1", "Proj/Team",
        {
            "teamMembers": [
                {
                    "teamMember": {"id": "u1", "displayName": "Alice"},
                    "activities": [{"name": "Dev", "capacityPerDay": 1}],
                    "daysOff": [
                        {"start": "2026-06-08T00:00:00Z", "end": "2026-06-08T00:00:00Z"}
                    ],
                }
            ]
        },
    )

    points = analytics_service.sprint_capacity_daily(repo, path)
    by_day = {p.day: p for p in points}

    assert len(points) == 5  # every calendar day of the sprint has a row
    assert by_day[date(2026, 6, 6)].capacity_hours == pytest.approx(0.0)  # Saturday
    assert by_day[date(2026, 6, 8)].capacity_hours == pytest.approx(0.0)  # day off
    # remaining: Fri 12h (Fri + Tue), flat 6h over Sat/Sun/Mon, Tue 6h
    assert by_day[date(2026, 6, 5)].remaining_capacity_hours == pytest.approx(12.0)
    assert by_day[date(2026, 6, 6)].remaining_capacity_hours == pytest.approx(6.0)
    assert by_day[date(2026, 6, 8)].remaining_capacity_hours == pytest.approx(6.0)
    assert by_day[date(2026, 6, 9)].remaining_capacity_hours == pytest.approx(6.0)


def test_burndown_summary_average_items_per_working_day(conn, repo):
    path = _seed_sprint(conn)  # 5 working days
    days = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
    snapshots = []
    # 4 tasks; items 1 and 2 are done from day 4 onward -> 2 done / 5 working days
    for day in days:
        for wi in range(1, 5):
            done = wi <= 2 and day >= days[3]
            state, cat = ("Done", "Completed") if done else ("Committed", "InProgress")
            snapshots.append(
                {
                    "WorkItemId": wi, "DateValue": f"{day}T00:00:00Z",
                    "WorkItemType": "Task", "State": state, "StateCategory": cat,
                }
            )
    loaders.upsert_work_item_snapshots(conn, path, snapshots, STATES)

    points = analytics_service.sprint_burndown_summary(repo, path)
    assert len(points) == 1
    p = points[0]
    assert p.work_item_type == "Task"
    assert p.end_date == date(2026, 6, 5)
    assert p.avg_burndown_items_per_day == pytest.approx(2 / 5)


def test_cycle_time_percentiles(conn, repo):
    path = _seed_sprint(conn)
    items = [
        {
            "WorkItemId": i, "WorkItemType": "Bug", "State": "Done",
            "StateCategory": "Completed", "CompletedDate": "2026-06-05T00:00:00Z",
            "CycleTimeDays": cycle, "LeadTimeDays": cycle + 1,
        }
        for i, cycle in enumerate([1, 2, 3, 4, 5], start=1)
    ]
    loaders.upsert_work_items(conn, "Proj", path, items, STATES)

    result = analytics_service.cycle_time_percentiles(repo, [path])
    assert len(result) == 1
    r = result[0]
    assert r.iteration_path == path
    assert r.end_date == date(2026, 6, 5)
    assert r.count == 5
    assert r.cycle_time_p50 == pytest.approx(3.0)


def test_scope_change_rate_for_items_added_mid_sprint(conn, repo):
    path = _seed_sprint(conn)
    days = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
    snapshots = []
    # Items 1-3 planned on day one; item 1 finishes by the last day.
    for day in days:
        for wi in range(1, 4):
            state, cat = ("Done", "Completed") if wi == 1 and day == days[-1] else (
                "Committed", "InProgress"
            )
            snapshots.append(
                {
                    "WorkItemId": wi, "DateValue": f"{day}T00:00:00Z",
                    "WorkItemType": "Task", "State": state, "StateCategory": cat,
                }
            )
    # Item 4 is pulled onto the board from day 3 onward — added mid-sprint.
    for day in days[2:]:
        snapshots.append(
            {
                "WorkItemId": 4, "DateValue": f"{day}T00:00:00Z", "WorkItemType": "Task",
                "State": "Committed", "StateCategory": "InProgress",
            }
        )
    loaders.upsert_work_item_snapshots(conn, path, snapshots, STATES)

    result = analytics_service.scope_change(repo, [path])
    assert len(result) == 1
    r = result[0]
    assert r.planned_items == 3
    assert r.added_items == 1
    assert r.final_scope_items == 4
    assert r.completed_items == 1
    assert r.scope_change_rate == pytest.approx(0.25)
    assert r.completion_rate == pytest.approx(0.25)
