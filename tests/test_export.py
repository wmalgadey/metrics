from datetime import date

import httpx
import respx

from metrics.export.vm import (
    push_to_victoriametrics,
    render_burndown,
    render_capacity,
    render_cycle_time,
    render_velocity,
)
from metrics.metrics.burndown import BurndownPoint
from metrics.metrics.capacity import CapacityPoint
from metrics.metrics.cycletime import CycleTimePercentiles
from metrics.metrics.velocity import VelocityPoint


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
