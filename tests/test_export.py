from datetime import UTC, date, datetime, timedelta

import httpx
import respx

from metrics.analytics.domain.model import (
    BurndownPoint,
    BurndownSummaryPoint,
    CapacityDayPoint,
    CapacityPoint,
    CycleTimePercentiles,
    EffortBurndownPoint,
    ScopeChangePoint,
    VelocityPoint,
)
from metrics.publishing.adapters.victoriametrics import push_to_victoriametrics
from metrics.publishing.domain.exposition import (
    render_burndown,
    render_burndown_summary,
    render_capacity,
    render_capacity_daily,
    render_cycle_time,
    render_effort_burndown,
    render_scope_change,
    render_velocity,
)


def test_render_burndown_includes_ideal_and_optional_effort():
    points = [
        BurndownPoint(
            iteration_path="Proj\\Sprint 1", work_item_type="Bug", day=date(2026, 6, 1),
            open_items=3, scope_items=3, done_items=0, ideal_open_items=3.0,
            remaining_effort=5.0, scope_effort=5.0, completed_effort=0.0,
        ),
        BurndownPoint(
            iteration_path="Proj\\Sprint 1", work_item_type="Task", day=date(2026, 6, 1),
            open_items=1, scope_items=1, done_items=0, ideal_open_items=1.0,
        ),
    ]
    lines = render_burndown(points, "Proj", "MyTeam")
    assert any(
        line.startswith("azdo_sprint_open_items{") and 'work_item_type="Bug"' in line
        for line in lines
    )
    assert any(line.startswith("azdo_sprint_remaining_effort{") for line in lines)
    # the Task point has no effort values -> no effort lines for it
    task_lines = [line for line in lines if 'work_item_type="Task"' in line]
    assert not any("effort" in line for line in task_lines)


def test_render_capacity_daily_emits_daily_and_remaining_hours():
    points = [
        CapacityDayPoint(
            iteration_path="Proj\\Sprint 1", day=date(2026, 6, 1),
            capacity_hours=6.0, remaining_capacity_hours=30.0,
        ),
        CapacityDayPoint(
            iteration_path="Proj\\Sprint 1", day=date(2026, 6, 2),
            capacity_hours=6.0, remaining_capacity_hours=24.0,
        ),
    ]
    lines = render_capacity_daily(points, "Proj", "MyTeam")

    assert len(lines) == 4
    assert all('sprint="Proj/Sprint 1"' in line for line in lines)
    day1_ts = str(int(datetime(2026, 6, 1, tzinfo=UTC).timestamp() * 1000))
    assert any(
        line.startswith("azdo_sprint_remaining_capacity_hours{")
        and line.endswith(f"30.0 {day1_ts}")
        for line in lines
    )
    assert any(line.startswith("azdo_sprint_capacity_day_hours{") for line in lines)


def test_render_effort_burndown_uses_estimated_metric_names():
    points = [
        EffortBurndownPoint(
            iteration_path="Proj\\Sprint 1", work_item_type="Product Backlog Item",
            day=date(2026, 6, 1), remaining_effort=12.0, scope_effort=12.0,
            completed_effort=0.0, estimated_items=1,
        ),
        EffortBurndownPoint(
            iteration_path="Proj\\Sprint 1", work_item_type="Task",
            day=date(2026, 6, 1), remaining_effort=None, scope_effort=None,
            completed_effort=None, estimated_items=0,
        ),
    ]
    lines = render_effort_burndown(points, "Proj", "MyTeam")

    assert any(line.startswith("azdo_sprint_remaining_effort_estimated{") for line in lines)
    assert any(line.startswith("azdo_sprint_scope_effort_estimated{") for line in lines)
    assert any(line.startswith("azdo_sprint_effort_estimated_items{") for line in lines)
    # never under the real-effort metric names
    assert not any(line.startswith("azdo_sprint_remaining_effort{") for line in lines)
    # the Task point has no effort sums -> only its estimated_items count line
    task_lines = [line for line in lines if 'work_item_type="Task"' in line]
    assert len(task_lines) == 1
    assert task_lines[0].startswith("azdo_sprint_effort_estimated_items{")


def test_render_burndown_summary_avg_items_per_day():
    points = [
        BurndownSummaryPoint(
            iteration_path="Proj\\Sprint 1", work_item_type="Task",
            end_date=date(2026, 6, 5), avg_burndown_items_per_day=0.4,
        )
    ]
    lines = render_burndown_summary(points, "Proj", "MyTeam")
    assert len(lines) == 1
    assert lines[0].startswith("azdo_sprint_avg_burndown_items_per_day{")
    assert 'work_item_type="Task"' in lines[0]


def test_render_velocity_and_capacity_and_cycletime():
    v = [
        VelocityPoint(
            iteration_path="Proj\\Sprint 1", work_item_type="Bug",
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 5),
            planned_items=4, completed_items=2, rolling_avg_items=2.0,
        )
    ]
    c = [
        CapacityPoint(
            iteration_path="Proj\\Sprint 1", start_date=date(2026, 6, 1), end_date=date(2026, 6, 5),
            capacity_hours=40.0, completed_items=2, items_per_capacity_hour=0.05,
        )
    ]
    ct = [
        CycleTimePercentiles(
            iteration_path="Proj\\Sprint 1", end_date=date(2026, 6, 5),
            work_item_type="Bug", count=5,
            cycle_time_p50=3.0, cycle_time_p85=4.5, cycle_time_p95=5.0,
            lead_time_p50=4.0, lead_time_p85=5.5, lead_time_p95=6.0,
        )
    ]
    v_lines = render_velocity(v, "Proj", "MyTeam")
    c_lines = render_capacity(c, "Proj", "MyTeam")
    ct_lines = render_cycle_time(ct, "Proj", "MyTeam")

    assert any(line.startswith("azdo_sprint_completed_items{") for line in v_lines)
    assert any(line.startswith("azdo_sprint_capacity_hours{") for line in c_lines)
    assert any(line.startswith("azdo_sprint_items_per_capacity_hour{") for line in c_lines)
    assert any('quantile="0.5"' in line for line in ct_lines)
    assert len(ct_lines) == 6  # 3 quantiles * (cycle + lead)
    end_ts = str(int(datetime(2026, 6, 5, tzinfo=UTC).timestamp() * 1000))
    assert all('sprint="Proj/Sprint 1"' in line for line in ct_lines)
    assert all(line.endswith(f" {end_ts}") for line in ct_lines)


def test_summary_timestamps_capped_at_today():
    # running/future sprints must not produce samples with future timestamps,
    # or they'd fall outside the dashboard's [now - duration, now] window
    future = date.today() + timedelta(days=7)
    today_ts = str(
        int(
            datetime.combine(
                datetime.now(tz=UTC).date(), datetime.min.time(), tzinfo=UTC
            ).timestamp()
            * 1000
        )
    )
    v = [
        VelocityPoint(
            iteration_path="Proj\\Sprint 9", work_item_type="Bug",
            start_date=future - timedelta(days=5), end_date=future,
            planned_items=1, completed_items=0, rolling_avg_items=0.0,
        ),
        VelocityPoint(
            iteration_path="Proj\\Sprint 10", work_item_type="Bug",
            start_date=None, end_date=None,
            planned_items=1, completed_items=0, rolling_avg_items=0.0,
        ),
    ]
    lines = render_velocity(v, "Proj", "MyTeam")
    assert lines
    assert all(line.endswith(f" {today_ts}") for line in lines)


def test_render_scope_change():
    sc = [
        ScopeChangePoint(
            iteration_path="Proj\\Sprint 1", work_item_type="Bug",
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 5),
            planned_items=3, added_items=1, final_scope_items=4, completed_items=1,
            scope_change_rate=0.25, completion_rate=0.25,
        ),
        ScopeChangePoint(
            iteration_path="Proj\\Sprint 2", work_item_type="Task",
            start_date=date(2026, 6, 8), end_date=date(2026, 6, 12),
            planned_items=0, added_items=0, final_scope_items=0, completed_items=0,
            scope_change_rate=None, completion_rate=None,
        ),
    ]
    lines = render_scope_change(sc, "Proj", "MyTeam")

    assert any(line.startswith("azdo_sprint_added_mid_sprint_items{") for line in lines)
    assert any(
        line.startswith("azdo_sprint_scope_change_rate{") and 'sprint="Proj/Sprint 1"' in line
        for line in lines
    )
    assert any(line.startswith("azdo_sprint_completion_rate{") for line in lines)
    # the Sprint 2 point has no rates (division by zero) -> no rate lines for it
    sprint2_lines = [line for line in lines if 'sprint="Proj/Sprint 2"' in line]
    assert not any("rate" in line for line in sprint2_lines)


@respx.mock
def test_push_to_victoriametrics_posts_exposition_format():
    route = respx.post("http://vm.local:8428/api/v1/import/prometheus").mock(
        return_value=httpx.Response(204)
    )
    push_to_victoriametrics("http://vm.local:8428", ['azdo_sprint_open_items{a="b"} 3 1000'])
    assert route.called
    request = route.calls[0].request
    assert b"azdo_sprint_open_items" in request.content


def test_push_to_victoriametrics_noop_on_empty_lines():
    # must not attempt any HTTP call
    push_to_victoriametrics("http://vm.local:8428", [])
