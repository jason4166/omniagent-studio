from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from omniagent.api import app, get_agent_profile_service, get_knowledge_base_service
from omniagent.repositories import InMemoryAgentProfileRepository, InMemoryKnowledgeRepository
from omniagent.services import AgentProfileService, KnowledgeBaseService

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def test_health_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    repository = InMemoryAgentProfileRepository()
    knowledge_repository = InMemoryKnowledgeRepository()

    def override_get_service() -> AgentProfileService:
        return AgentProfileService(repository)

    def override_get_knowledge_service() -> KnowledgeBaseService:
        return KnowledgeBaseService(knowledge_repository)

    app.dependency_overrides[get_agent_profile_service] = override_get_service
    app.dependency_overrides[get_knowledge_base_service] = override_get_knowledge_service

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


def create_demo_knowledge_base(client: TestClient) -> None:
    response = client.post(
        "/api/knowledge-bases",
        json={"knowledge_base_id": "kb-demo", "name": "Synthetic Demo"},
    )
    assert response.status_code == 201


def test_create_knowledge_base_returns_201(client: TestClient) -> None:
    response = client.post(
        "/api/knowledge-bases",
        json={"knowledge_base_id": "kb-demo", "name": "Synthetic Demo"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "knowledge_base_id": "kb-demo",
        "name": "Synthetic Demo",
    }


def test_upload_txt_returns_source_status_and_checksum(client: TestClient) -> None:
    create_demo_knowledge_base(client)
    raw_bytes = (FIXTURES / "synthetic-policy.txt").read_bytes()

    response = client.post(
        "/api/knowledge-bases/kb-demo/sources",
        files={"file": ("synthetic-policy.txt", raw_bytes, "text/plain")},
    )

    body = response.json()
    assert response.status_code == 201
    assert body["status"] == "imported"
    assert body["source_name"] == "synthetic-policy.txt"
    assert body["source_id"].startswith("src-")
    assert len(body["checksum"]) == 64
    assert body["chunk_count"] == 1
    assert body["error"] is None


def test_repeated_upload_returns_duplicate_without_new_chunks(client: TestClient) -> None:
    create_demo_knowledge_base(client)
    raw_bytes = (FIXTURES / "synthetic-policy.txt").read_bytes()
    files = {"file": ("synthetic-policy.txt", raw_bytes, "text/plain")}

    first_response = client.post("/api/knowledge-bases/kb-demo/sources", files=files)
    second_response = client.post("/api/knowledge-bases/kb-demo/sources", files=files)

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["status"] == "duplicate"
    assert second_response.json()["source_id"] == first_response.json()["source_id"]
    assert second_response.json()["chunk_count"] == first_response.json()["chunk_count"]


def test_upload_scanned_pdf_returns_unsupported_without_path_leak(client: TestClient) -> None:
    create_demo_knowledge_base(client)
    raw_bytes = (FIXTURES / "synthetic-scanned-page.pdf").read_bytes()

    response = client.post(
        "/api/knowledge-bases/kb-demo/sources",
        files={
            "file": (
                "C:\\private\\synthetic-scanned-page.pdf",
                raw_bytes,
                "application/pdf",
            )
        },
    )

    body = response.json()
    assert response.status_code == 422
    assert body["status"] == "unsupported"
    assert body["source_name"] == "synthetic-scanned-page.pdf"
    assert body["error"] == {
        "code": "scanned_pdf_unsupported",
        "message": "PDF has no extractable text; OCR is not supported",
    }
    assert "C:\\private" not in response.text


@pytest.mark.parametrize(
    ("filename", "mime_type", "expected_code"),
    [
        ("synthetic.csv", "text/csv", "unsupported_extension"),
        ("synthetic.txt", "application/pdf", "mime_type_mismatch"),
    ],
)
def test_upload_rejects_unsupported_extension_or_mime(
    client: TestClient,
    filename: str,
    mime_type: str,
    expected_code: str,
) -> None:
    create_demo_knowledge_base(client)

    response = client.post(
        "/api/knowledge-bases/kb-demo/sources",
        files={"file": (filename, b"synthetic", mime_type)},
    )

    assert response.status_code == 415
    assert response.json()["status"] == "rejected"
    assert response.json()["error"]["code"] == expected_code


def test_upload_rejects_file_over_size_limit(client: TestClient) -> None:
    create_demo_knowledge_base(client)
    raw_bytes = b"x" * (KnowledgeBaseService.MAX_UPLOAD_BYTES + 1)

    response = client.post(
        "/api/knowledge-bases/kb-demo/sources",
        files={"file": ("large.txt", raw_bytes, "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["status"] == "rejected"
    assert response.json()["error"]["code"] == "upload_too_large"


def test_upload_returns_404_for_missing_knowledge_base(client: TestClient) -> None:
    response = client.post(
        "/api/knowledge-bases/missing/sources",
        files={"file": ("synthetic.txt", b"synthetic", "text/plain")},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "knowledge_base_not_found",
            "message": "Knowledge base 'missing' was not found",
        }
    }
