import json
import socket

import httpx
import pytest

from omniagent.connectors import catalog
from omniagent.http_tools import HTTPConnectorConfig, HTTPToolAdapter, import_openapi_subset
from omniagent.tooling import ToolBusinessError

pytestmark = pytest.mark.contract


def config() -> HTTPConnectorConfig:
    return catalog("127.0.0.1", 18081)[1]["lookup_product"]


def adapter(handler) -> HTTPToolAdapter:
    return HTTPToolAdapter(
        config(),
        approved_origins=frozenset({("127.0.0.1", 18081)}),
        local_mock_hosts=frozenset({"127.0.0.1"}),
        transport=httpx.MockTransport(handler),
    )


def test_http_dials_verified_host_and_only_sends_business_parameters() -> None:
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"sku": "P-100"})

    assert adapter(handler).execute({"sku": "P-100"}) == {"sku": "P-100"}
    assert captured[0].url.host == "127.0.0.1"
    assert captured[0].url.path == "/tools/lookup_product"
    assert dict(captured[0].url.params) == {"sku": "P-100"}


@pytest.mark.parametrize("field", ["url", "host", "path", "method", "headers", "Authorization"])
def test_model_cannot_control_transport(field: str) -> None:
    requests = []
    with pytest.raises(ToolBusinessError, match="parameters"):
        adapter(lambda request: requests.append(request)).execute({"sku": "P-100", field: "evil"})
    assert not requests


@pytest.mark.parametrize(
    "address",
    ["169.254.169.254", "127.0.0.2", "10.0.0.1", "0.0.0.0", "224.0.0.1"],  # noqa: S104
)
def test_dns_private_metadata_and_multicast_are_blocked(monkeypatch, address) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *_args, **_kwargs: [(0, 0, 0, "", (address, 80))]
    )
    with pytest.raises(ValueError, match="forbidden"):
        HTTPToolAdapter(config(), approved_origins=frozenset({("127.0.0.1", 18081)}))


@pytest.mark.parametrize("status", [301, 302, 307, 308, 404, 422, 429, 500, 503])
def test_http_errors_are_bounded_and_not_implicitly_retried(status) -> None:
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"location": "http://169.254.169.254/"}, json={})

    with pytest.raises(ToolBusinessError):
        adapter(handler).execute({"sku": "P-100"})
    assert calls == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>unexpected</html>"),
        httpx.Response(200, content=b"not json", headers={"content-type": "application/json"}),
        httpx.Response(200, json={"large": "x" * 17000}),
        httpx.Response(200, json=["wrong schema"]),
    ],
)
def test_response_contract_is_enforced(response) -> None:
    with pytest.raises(ToolBusinessError):
        adapter(lambda _request: response).execute({"sku": "P-100"})


def test_timeout_maps_without_leaking_dependency_details() -> None:
    def handler(_request):
        raise httpx.ReadTimeout("private upstream information")

    with pytest.raises(TimeoutError, match="Connector timed out"):
        adapter(handler).execute({"sku": "P-100"})


def specification() -> dict[str, object]:
    approved = config()
    fields = approved.parameters_schema["properties"]
    return {
        "openapi": "3.1.0",
        "info": {"title": "Synthetic", "version": "1"},
        "paths": {
            approved.path: {
                "get": {
                    "operationId": "lookup_product",
                    "parameters": [
                        {"name": name, "in": "query", "required": True, "schema": field}
                        for name, field in fields.items()
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }


def test_controlled_openapi_import() -> None:
    imported = import_openapi_subset(specification(), {"lookup_product": config()})
    assert imported["lookup_product"] == config()


@pytest.mark.parametrize("mutation", ["server", "reference", "method", "path", "header", "schema"])
def test_openapi_cannot_expand_approved_destinations(mutation) -> None:
    document = specification()
    operation = document["paths"][config().path]["get"]
    if mutation == "server":
        document["servers"] = [{"url": "http://localhost/admin"}]
    elif mutation == "reference":
        operation["parameters"][0]["schema"] = {"$ref": "http://evil/schema"}
    elif mutation == "method":
        document["paths"][config().path] = {"delete": operation}
    elif mutation == "path":
        document["paths"] = {"/admin": {"get": operation}}
    elif mutation == "header":
        operation["parameters"][0]["in"] = "header"
    else:
        operation["parameters"][0]["schema"] = {"type": "integer"}
    with pytest.raises(ValueError):
        import_openapi_subset(json.loads(json.dumps(document)), {"lookup_product": config()})
