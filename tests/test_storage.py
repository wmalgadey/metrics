from datetime import date

import duckdb
import pytest

from metrics.config import StatesConfig
from metrics.shared.duckdb.db import apply_schema
from metrics.storage import loaders

STATES = StatesConfig(
    done=["Done", "Closed"],
    in_progress=["Committed", "In Progress"],
    removed=["Removed"],
)


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    apply_schema(c)
    yield c
    c.close()


def test_schema_is_idempotent(conn):
    apply_schema(conn)  # second run must not raise
    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    assert {"projects", "teams", "iterations", "work_items", "work_item_snapshots"} <= tables


@pytest.mark.parametrize(
    "state,category,expected",
    [
        ("Removed", "Proposed", "Removed"),
        ("Done", "Completed", "Completed"),
        ("Committed", "InProgress", "InProgress"),
        ("New", "Proposed", "Proposed"),  # falls back to Analytics' own category
    ],
)
def test_classify_state(state, category, expected):
    assert loaders.classify_state(state, category, STATES) == expected


def _seed_project_team_iteration(conn, iteration_id="it-1", path="Proj\\Sprint 1"):
    loaders.upsert_project(conn, "Proj", "my-org")
    loaders.upsert_team(conn, "Proj/Team", "Proj", "Team")
    loaders.upsert_iterations(
        conn,
        "Proj",
        "Proj/Team",
        [
            {
                "id": iteration_id,
                "name": "Sprint 1",
                "path": path,
                "attributes": {
                    "startDate": "2026-06-01T00:00:00Z",
                    "finishDate": "2026-06-02T00:00:00Z",
                    "timeFrame": "past",
                },
            }
        ],
        {path},
    )


def test_upsert_work_items_is_idempotent(conn):
    _seed_project_team_iteration(conn)
    item = {
        "WorkItemId": 1,
        "WorkItemType": "Product Backlog Item",
        "Title": "Do the thing",
        "State": "Done",
        "StateCategory": "Completed",
        "IterationSK": "it-1",
        "Effort": 3,
        "CreatedDate": "2026-06-01T00:00:00Z",
        "ClosedDate": "2026-06-02T00:00:00Z",
        "CompletedDate": "2026-06-02T00:00:00Z",
        "ChangedDate": "2026-06-02T00:00:00Z",
        "CycleTimeDays": 1,
        "LeadTimeDays": 1,
    }
    n1 = loaders.upsert_work_items(conn, "Proj", "Proj\\Sprint 1", [item], STATES)
    n2 = loaders.upsert_work_items(conn, "Proj", "Proj\\Sprint 1", [item], STATES)
    assert n1 == n2 == 1
    count = conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0]
    assert count == 1
    row = conn.execute(
        "SELECT effective_category, effort FROM work_items WHERE work_item_id = 1"
    ).fetchone()
    assert row == ("Completed", 3)


def test_upsert_snapshots_and_burndown_view(conn):
    _seed_project_team_iteration(conn)
    snapshots = [
        {
            "WorkItemId": 1,
            "DateValue": "2026-06-01T00:00:00Z",
            "WorkItemType": "Product Backlog Item",
            "State": "Committed",
            "StateCategory": "InProgress",
            "Effort": 3,
        },
        {
            "WorkItemId": 2,
            "DateValue": "2026-06-01T00:00:00Z",
            "WorkItemType": "Bug",
            "State": "Removed",
            "StateCategory": "Removed",
            "Effort": 1,
        },
        {
            "WorkItemId": 1,
            "DateValue": "2026-06-02T00:00:00Z",
            "WorkItemType": "Product Backlog Item",
            "State": "Done",
            "StateCategory": "Completed",
            "Effort": 3,
        },
    ]
    loaders.upsert_work_item_snapshots(conn, "Proj\\Sprint 1", snapshots, STATES)
    # re-run to check idempotency (upsert, not duplicate rows)
    loaders.upsert_work_item_snapshots(conn, "Proj\\Sprint 1", snapshots, STATES)

    rows = conn.execute(
        """
        SELECT snapshot_date, open_items, scope_items, done_items
        FROM v_sprint_burndown
        WHERE iteration_path = 'Proj\\Sprint 1' AND work_item_type = 'Product Backlog Item'
        ORDER BY snapshot_date
        """
    ).fetchall()
    assert rows == [(date(2026, 6, 1), 1, 1, 0), (date(2026, 6, 2), 0, 1, 1)]

    # the Removed bug must not count toward scope
    bug_rows = conn.execute(
        "SELECT scope_items FROM v_sprint_burndown WHERE work_item_type = 'Bug'"
    ).fetchall()
    assert bug_rows == [(0,)]


def test_capacity_view_excludes_days_off_and_weekends(conn):
    _seed_project_team_iteration(conn, iteration_id="it-2", path="Proj\\Sprint 2")
    # widen the iteration to a full week to exercise weekend exclusion
    conn.execute(
        "UPDATE iterations SET start_date = '2026-06-01', end_date = '2026-06-07' "
        "WHERE iteration_id = 'it-2'"
    )  # Mon 2026-06-01 .. Sun 2026-06-07
    loaders.upsert_capacities(
        conn,
        "it-2",
        "Proj/Team",
        {
            "teamMembers": [
                {
                    "teamMember": {"id": "u1", "displayName": "Alice"},
                    "activities": [{"name": "Dev", "capacityPerDay": 8}],
                    "daysOff": [{"start": "2026-06-03T00:00:00Z", "end": "2026-06-03T00:00:00Z"}],
                }
            ]
        },
    )
    capacity = conn.execute(
        "SELECT capacity_hours FROM v_capacity WHERE iteration_path = 'Proj\\Sprint 2'"
    ).fetchone()[0]
    # Mon-Fri = 5 weekdays, minus 1 day off (Wed) = 4 days * 8h = 32h
    assert capacity == 32
