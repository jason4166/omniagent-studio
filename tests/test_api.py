from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from omniagent.api import app, get_agent_profile_service
from omniagent.repositories import InMemoryAgentProfileRepository
from omniagent.services import AgentProfileService


def test_health_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    repository = InMemoryAgentProfileRepository()

    def override_get_service() -> AgentProfileService:
        return AgentProfileService(repository)

    app.dependency_overrides[get_agent_profile_service] = override_get_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_create_agent_returns_201(client: TestClient) -> None:
    payload = {
        "profile_id": "sales",
        "prompt_version_id": "sales:v1",
        "budget_policy_id": "standard",
        "approval_policy_id": "safe-default",
    }

    response = client.post("/api/agents", json=payload)

    assert response.status_code == 201
    assert response.json() == {
        "profile_id": "sales",
        "version": 1,
        "enabled": True,
        "tool_ids": [],
        "knowledge_base_ids": [],
        "prompt_version_id": "sales:v1",
        "budget_policy_id": "standard",
        "approval_policy_id": "safe-default",
    }


def test_create_agent_rejects_missing_prompt_version_id(
    client: TestClient,
) -> None:
    payload = {
        "profile_id": "sales",
        "budget_policy_id": "standard",
        "approval_policy_id": "safe-default",
    }
    response = client.post("/api/agents", json=payload)
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "request_validation_error",
            "message": "Request validation failed",
        }
    }


def test_create_agent_returns_409_for_duplicate_profile(
    client: TestClient,
) -> None:
    payload = {
        "profile_id": "sales",
        "prompt_version_id": "sales:v1",
        "budget_policy_id": "standard",
        "approval_policy_id": "safe-default",
    }

    first_response = client.post("/api/agents", json=payload)
    second_response = client.post("/api/agents", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json() == {
        "error": {
            "code": "agent_already_exists",
            "message": "Agent profile 'sales' already exists",
        }
    }


def test_get_agent_returns_created_profile(
    client: TestClient,
) -> None:
    payload = {
        "profile_id": "sales",
        "prompt_version_id": "sales:v1",
        "budget_policy_id": "standard",
        "approval_policy_id": "safe-default",
    }

    create_response = client.post("/api/agents", json=payload)
    get_response = client.get("/api/agents/sales")

    assert create_response.status_code == 201
    assert get_response.status_code == 200
    assert get_response.json() == create_response.json()


def test_get_agent_returns_404_when_profile_is_missing(
    client: TestClient,
) -> None:
    response = client.get("/api/agents/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "agent_not_found",
            "message": "Agent profile 'missing' was not found",
        }
    }


def test_update_agent_returns_new_version(
    client: TestClient,
) -> None:
    payload = {
        "profile_id": "sales",
        "prompt_version_id": "sales:v1",
        "budget_policy_id": "standard",
        "approval_policy_id": "safe-default",
    }
    create_response = client.post("/api/agents", json=payload)
    assert create_response.status_code == 201
    patch_payload = {
        "expected_version": 1,
        "tool_ids": ["search"],
    }

    patch_response = client.patch(
        "/api/agents/sales",
        json=patch_payload,
    )
    assert patch_response.status_code == 200

    patch_body = patch_response.json()

    assert patch_body["profile_id"] == "sales"
    assert patch_body["version"] == 2
    assert patch_body["tool_ids"] == ["search"]
    get_response = client.get("/api/agents/sales")

    assert get_response.status_code == 200
    assert get_response.json() == patch_body


def test_update_agent_returns_409_for_stale_version(
    client: TestClient,
) -> None:
    payload = {
        "profile_id": "sales",
        "prompt_version_id": "sales:v1",
        "budget_policy_id": "standard",
        "approval_policy_id": "safe-default",
    }
    create_response = client.post("/api/agents", json=payload)
    assert create_response.status_code == 201
    patch_payload = {
        "expected_version": 1,
        "tool_ids": ["search"],
    }
    first_patch_response = client.patch(
        "/api/agents/sales",
        json=patch_payload,
    )
    assert first_patch_response.status_code == 200
    assert first_patch_response.json()["version"] == 2
    stale_patch_payload = {
        "expected_version": 1,
        "tool_ids": ["calculator"],
    }

    stale_patch_response = client.patch(
        "/api/agents/sales",
        json=stale_patch_payload,
    )
    assert stale_patch_response.status_code == 409
    assert stale_patch_response.json() == {
        "error": {
            "code": "agent_version_conflict",
            "message": ("Agent profile 'sales' version conflict: expected 1, current 2"),
        }
    }
    get_response = client.get("/api/agents/sales")

    assert get_response.status_code == 200
    assert get_response.json() == first_patch_response.json()
