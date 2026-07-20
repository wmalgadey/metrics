import httpx
import respx

from metrics.azdo.http import make_client
from metrics.azdo.odata import ODataClient
from metrics.config import AzureDevOpsConfig

CFG = AzureDevOpsConfig(organization="my-org", project="MyProject", team="MyTeam")
BASE = CFG.analytics_url


@respx.mock
def test_work_items_follows_next_link(load_fixture):
    route = respx.get(f"{BASE}/WorkItems")
    route.side_effect = [
        httpx.Response(200, json=load_fixture("work_items_page1.json")),
        httpx.Response(200, json=load_fixture("work_items_page2.json")),
    ]

    with make_client("fake-pat") as client:
        odata = ODataClient(client, CFG)
        items = list(odata.work_items("MyProject\\Sprint 23"))

    assert route.call_count == 2
    assert [i["WorkItemId"] for i in items] == [101, 102]
    assert items[1]["CycleTimeDays"] == 4


@respx.mock
def test_work_item_snapshots(load_fixture):
    respx.get(f"{BASE}/WorkItemSnapshot").mock(
        return_value=httpx.Response(200, json=load_fixture("work_item_snapshots.json"))
    )

    with make_client("fake-pat") as client:
        odata = ODataClient(client, CFG)
        from datetime import date

        snapshots = list(
            odata.work_item_snapshots("MyProject\\Sprint 23", date(2026, 6, 1), date(2026, 6, 14))
        )

    assert len(snapshots) == 4
    assert {s["WorkItemId"] for s in snapshots} == {101, 102}


@respx.mock
def test_retries_on_429_then_succeeds(load_fixture):
    route = respx.get(f"{BASE}/WorkItems")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json=load_fixture("work_items_page2.json")),
    ]

    with make_client("fake-pat") as client:
        odata = ODataClient(client, CFG)
        items = list(odata.work_items("MyProject\\Sprint 23"))

    assert len(items) == 1
    assert route.call_count == 2
