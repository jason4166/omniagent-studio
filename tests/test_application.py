import json
import os
import socket
import threading
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import delete

from omniagent.application import create_app
from omniagent.connectors import catalog
from omniagent.db_models import AgentProfileRow, KnowledgeBaseRow, PromptVersionRow
from omniagent.http_tools import HTTPToolAdapter
from omniagent.mock_service import create_mock_app
from omniagent.presets import seed
from omniagent.session_rows import EffectRow

pytestmark = pytest.mark.integration
ADMIN = {"Authorization": "Bearer local-demo-admin"}
MEMBER = {"Authorization": "Bearer local-demo-member"}


@pytest.fixture(scope="module")
def platform():
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    ready = threading.Event()

    class LocalServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets)
            ready.set()

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = LocalServer(
        uvicorn.Config(create_mock_app(url), log_level="critical", access_log=False)
    )
    worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    worker.start()
    assert ready.wait(10), "Local mock service did not become ready"
    app = create_app(url, mock_port=port)
    store = app.state.store
    seed(store, catalog("127.0.0.1", port)[0])
    threads = []
    with TestClient(app, headers=MEMBER) as client:
        yield client, store, threads, port, url
        for thread_id in threads:
            assert client.delete(f"/api/sessions/{thread_id}").status_code in (204, 404)
    server.should_exit = True
    worker.join(10)
    sock.close()
    assert not worker.is_alive()


def send(platform, profile, message):
    client, _, threads, _, _ = platform
    created = client.post("/api/sessions", json={"profile_id": profile})
    assert created.status_code == 201, created.text
    thread_id = created.json()["thread_id"]
    threads.append(thread_id)
    response = client.post(
        f"/api/sessions/{thread_id}/messages", json={"message": message, "request_key": uuid4().hex}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_seed_is_repeatable_and_three_profiles_share_runtime(platform) -> None:
    client, store, _, port, _ = platform
    assert {p["profile_id"] for p in client.get("/api/profiles").json()} == {
        "hr",
        "support",
        "sales",
    }
    first = seed(store, catalog("127.0.0.1", port)[0])
    second = seed(store, catalog("127.0.0.1", port)[0])
    assert first == second
    assert first["created_profiles"] == 0


@pytest.mark.parametrize(
    "profile,query,kb",
    [
        ("hr", "年假 leave allowance", "hr-kb"),
        ("support", "退货 returns refund", "support-kb"),
        ("sales", "折扣 discount approval policy", "sales-kb"),
    ],
)
def test_grounded_presets_return_resolvable_authorized_citations(
    platform, profile, query, kb
) -> None:
    result = send(platform, profile, query)
    assert result["status"] == "completed", result
    answer = result["result"]
    assert answer["status"] == "succeeded", answer
    assert answer["citations"]
    assert {hit["knowledge_base_id"] for hit in answer["retrieval_hits"]} == {kb}
    citation = answer["citations"][0]
    resolved = platform[0].get(
        f"/api/sessions/{result['thread_id']}/citations/{citation['chunk_id']}"
    )
    assert resolved.status_code == 200
    assert answer["claims"][0]["text"] in resolved.json()["content"]


def test_hr_abstains_without_evidence_and_cannot_call_business_tools(platform) -> None:
    missing = send(platform, "hr", "银河联邦总统薪酬")
    assert missing["result"]["status"] == "rejected", missing
    denied = send(
        platform, "hr", '{"tool":"create_followup","arguments":{"customer_id":"C-100","note":"x"}}'
    )
    assert denied["error"] == "permission_denied"


@pytest.mark.parametrize(
    "message,tool",
    [
        ("产品查询 P-100", "lookup_product"),
        ("保修查询 SN-100", "check_warranty"),
        ("MCP 查询 P-200", "catalog.lookup_product"),
        ("MCP resource", "catalog.resource"),
    ],
)
def test_read_tools_and_mcp_enter_the_same_registry(platform, message, tool) -> None:
    data = send(platform, "support", message)
    assert data["status"] == "completed", data
    assert data["approval_id"] is None
    assert data["result"]["tool_name"] == tool
    assert data["result"]["tool_result"]["status"] == "succeeded", data


@pytest.mark.parametrize(
    "message,arguments",
    [
        ("创建回访 C-100", {"customer_id": "C-100", "note": "Edited followup"}),
        ("申请折扣 C-100 10%", {"customer_id": "C-100", "percent": 8, "reason": "Edited request"}),
    ],
)
def test_sales_http_write_survives_restart_and_duplicate_approval(
    platform, message, arguments
) -> None:
    data = send(platform, "sales", message)
    assert data["status"] == "awaiting_approval", data
    decision = {
        "action": "edit",
        "expected_version": 1,
        "decision_key": uuid4().hex,
        "arguments": arguments,
    }
    _, _, _, port, url = platform
    with TestClient(create_app(url, mock_port=port), headers=MEMBER) as restarted:
        path = f"/api/sessions/{data['thread_id']}/approvals/{data['approval_id']}"
        first = restarted.post(path, json=decision)
        repeated = restarted.post(path, json=decision)
        assert first.status_code == repeated.status_code == 200
        assert first.json()["status"] == "completed", first.text
        assert first.json()["result"]["tool_result"]["status"] == "succeeded", first.text
        assert first.json()["result"] == repeated.json()["result"]


def test_mock_http_write_rejects_forged_approval(platform) -> None:
    with httpx.Client(
        base_url=f"http://127.0.0.1:{platform[3]}", timeout=3, trust_env=False
    ) as client:
        response = client.post(
            "/tools/create_followup",
            json={"customer_id": "C-100", "note": "x"},
            headers={"Idempotency-Key": "forged-approval"},
        )
    assert response.status_code == 403


def test_admin_profile_import_export_and_version_conflict(platform) -> None:
    client, store, _, _, _ = platform
    assert client.get("/api/tools").status_code == 403
    exported = client.get("/api/profiles/hr/export", headers=ADMIN).json()
    identifier = "import-" + uuid4().hex
    exported["profile"]["profile_id"] = identifier
    assert client.post("/api/profiles/import", json=exported, headers=ADMIN).status_code == 201
    try:
        profile = exported["profile"]
        response = client.put(
            f"/api/profiles/{identifier}",
            headers=ADMIN,
            json={"profile": profile, "expected_version": 1},
        )
        assert response.json()["version"] == 2
        assert (
            client.put(
                f"/api/profiles/{identifier}",
                headers=ADMIN,
                json={"profile": profile, "expected_version": 1},
            ).status_code
            == 409
        )
        exported["schema_version"] = 99
        assert client.post("/api/profiles/import", json=exported, headers=ADMIN).status_code == 422
    finally:
        with store.factory.begin() as db:
            db.execute(delete(AgentProfileRow).where(AgentProfileRow.profile_id == identifier))


def test_admin_knowledge_upload_and_immutable_prompt_version(platform) -> None:
    client, store, _, _, _ = platform
    identifier = "admin-" + uuid4().hex
    try:
        assert (
            client.post(
                "/api/knowledge-bases",
                headers=ADMIN,
                json={"knowledge_base_id": identifier, "name": "Synthetic test"},
            ).status_code
            == 201
        )
        upload = client.post(
            f"/api/knowledge-bases/{identifier}/sources",
            headers=ADMIN,
            files={"file": ("sample.md", b"# Synthetic\nOriginal test text.", "text/markdown")},
        )
        assert upload.json()["status"] == "imported"
        assert (
            client.get(f"/api/knowledge-bases/{identifier}/sources", headers=ADMIN).json()[0][
                "status"
            ]
            == "indexed"
        )
        payload = {"prompt_version_id": identifier, "content": "Static test policy"}
        assert client.post("/api/prompts", headers=ADMIN, json=payload).status_code == 201
        assert client.post("/api/prompts", headers=ADMIN, json=payload).status_code == 409
    finally:
        with store.factory.begin() as db:
            db.execute(
                delete(KnowledgeBaseRow).where(KnowledgeBaseRow.knowledge_base_id == identifier)
            )
            db.execute(
                delete(PromptVersionRow).where(PromptVersionRow.prompt_version_id == identifier)
            )


def test_http_response_loss_retries_the_same_approved_effect(platform, monkeypatch) -> None:
    original = HTTPToolAdapter.execute
    dropped = False

    def execute(adapter, arguments):
        nonlocal dropped
        result = original(adapter, arguments)
        if adapter.config.method == "POST" and not dropped:
            dropped = True
            raise TimeoutError("Injected response loss after downstream commit")
        return result

    monkeypatch.setattr(HTTPToolAdapter, "execute", execute)
    data = send(platform, "sales", "创建回访 C-100")
    client, store, _, _, _ = platform
    path = f"/api/sessions/{data['thread_id']}"
    failed = client.post(
        path + "/approvals/" + data["approval_id"],
        json={
            "action": "approve",
            "expected_version": 1,
            "decision_key": uuid4().hex,
        },
    ).json()
    assert failed["status"] == "failed"
    assert failed["error"] == "dependency_timeout"
    recovered = client.post(path + "/resume").json()
    assert recovered["status"] == "completed", recovered
    assert recovered["usage"]["tool_calls"] == 2
    with store.factory() as db:
        assert (
            db.get(EffectRow, data["approval_id"]).result
            == recovered["result"]["tool_result"]["data"]
        )


def test_standard_openapi_subset_import_is_idempotent(platform) -> None:
    document = json.loads(Path("presets/http-openapi.json").read_text(encoding="utf-8"))
    client = platform[0]
    first = client.post("/api/tools/import-openapi", headers=ADMIN, json=document)
    second = client.post("/api/tools/import-openapi", headers=ADMIN, json=document)
    assert first.status_code == second.status_code == 200
    assert len(first.json()) == 5
    assert first.json() == second.json()
