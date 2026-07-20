import httpx
import pytest
import respx

from metrics.config import AzureDevOpsConfig
from metrics.ingestion.adapters.azdo.http import AzdoHttpError, get_json, make_client
from metrics.ingestion.adapters.azdo.rest import RestClient

CFG = AzureDevOpsConfig(organization="my-org", project="MyProject", team="MyTeam")


@respx.mock
def test_list_iterations(load_fixture):
    respx.get(
        "https://dev.azure.com/my-org/MyProject/MyTeam/_apis/work/teamsettings/iterations"
    ).mock(return_value=httpx.Response(200, json=load_fixture("iterations.json")))

    with make_client("fake-pat") as client:
        rest = RestClient(client, CFG)
        iterations = rest.list_iterations()

    assert len(iterations) == 2
    assert iterations[0]["path"] == "MyProject\\Sprint 23"


@respx.mock
def test_get_capacities(load_fixture):
    iteration_id = "11111111-1111-1111-1111-111111111111"
    respx.get(
        f"https://dev.azure.com/my-org/MyProject/MyTeam/_apis/work/teamsettings/"
        f"iterations/{iteration_id}/capacities"
    ).mock(return_value=httpx.Response(200, json=load_fixture("capacities.json")))

    with make_client("fake-pat") as client:
        rest = RestClient(client, CFG)
        capacities = rest.get_capacities(iteration_id)

    assert len(capacities["teamMembers"]) == 2
    assert capacities["teamMembers"][0]["activities"][0]["capacityPerDay"] == 6


@respx.mock
def test_auth_failure_raises_helpful_error():
    respx.get("https://dev.azure.com/_apis/projects").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )

    with make_client("bad-pat") as client, pytest.raises(AzdoHttpError) as exc_info:
        get_json(client, "https://dev.azure.com/_apis/projects")
    assert "401" in str(exc_info.value)
    assert "scopes" in str(exc_info.value)
