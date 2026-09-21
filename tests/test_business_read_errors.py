import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from omniagent import mock_service

pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("lookup_product", {"sku": "P-999"}),
        ("check_warranty", {"serial_number": "SN-999"}),
        ("lookup_customer", {"customer_id": "C-999"}),
    ],
)
def test_mock_read_errors_distinguish_missing_records_from_endpoints(
    monkeypatch, operation, arguments
):
    monkeypatch.setattr(mock_service, "build_engine", lambda _: create_engine("sqlite://"))
    with TestClient(mock_service.create_mock_app("sqlite://")) as client:
        response = client.get(f"/tools/{operation}", params=arguments)
        assert response.status_code == 404
        assert response.json() == {
            "detail": {
                "code": "record_not_found",
                "operation": operation,
                "arguments": arguments,
            }
        }
        missing_endpoint = client.get("/tools/unknown", params=arguments)
        assert missing_endpoint.status_code == 404
        assert missing_endpoint.json() == {"detail": "Unknown read operation"}
        invalid = client.get(f"/tools/{operation}")
        assert invalid.status_code == 422
