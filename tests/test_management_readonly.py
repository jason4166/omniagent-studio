"""Read-only management is scoped by Profile authorization, not just hidden UI buttons."""

from uuid import uuid4

import pytest

from omniagent.access import AccountInput
from omniagent.db_models import AgentProfileRow
from test_public_access import PASSWORD, login
from test_public_access import public_app as public_app

pytestmark = [pytest.mark.integration, pytest.mark.security]


@pytest.fixture
def reviewer_app(public_app):
    app, access, accounts = public_app
    accounts["reviewer"] = access.create_account(
        AccountInput(
            username="review-" + uuid4().hex,
            password=PASSWORD,
            role="reviewer",
            profile_ids=["hr"],
        )
    )
    reviewer, _ = login(app, accounts["reviewer"])
    administrator, _ = login(app, accounts["admin"])
    return app, access, accounts, reviewer, administrator


def test_reviewer_reads_only_authorized_configuration(reviewer_app):
    _, _, _, client, administrator = reviewer_app
    profile = client.get("/api/profiles/hr").json()
    assert [p["profile_id"] for p in client.get("/api/profiles").json()] == ["hr"]
    assert client.get("/api/profiles/hr/export").json()["profile"] == profile
    assert {kb["knowledge_base_id"] for kb in client.get("/api/knowledge-bases").json()} == set(
        profile["knowledge_base_ids"]
    )
    for kb in profile["knowledge_base_ids"]:
        response = client.get(f"/api/knowledge-bases/{kb}/sources")
        assert response.status_code == 200 and response.json()
    assert client.get("/api/tools").json() == []
    assert [p["prompt_version_id"] for p in client.get("/api/prompts").json()] == [
        profile["prompt_version_id"]
    ]
    assert [p["provider_id"] for p in client.get("/api/providers").json()] == [
        profile["provider_id"]
    ]
    support = administrator.get("/api/profiles/support").json()
    for path in [
        "/api/profiles/support",
        "/api/profiles/support/export",
        f"/api/knowledge-bases/{support['knowledge_base_ids'][0]}/sources",
    ]:
        assert client.get(path).status_code in (403, 404)


@pytest.mark.parametrize("path", ["accounts", "audit", "metrics", "telemetry"])
def test_reviewer_cannot_read_accounts_or_global_operational_data(reviewer_app, path):
    _, _, _, client, administrator = reviewer_app
    assert client.get("/api/" + path, headers={"X-Role": "admin"}).status_code == 403
    assert administrator.get("/api/" + path).status_code == 200


@pytest.mark.parametrize(
    "operation",
    [
        "create-profile",
        "update-profile",
        "validate-profile",
        "import-profile",
        "create-kb",
        "upload",
        "save-tool",
        "import-openapi",
        "create-prompt",
        "create-account",
        "update-account",
    ],
)
def test_management_mutations_reject_reviewer_even_with_valid_requests(reviewer_app, operation):
    _, _, accounts, client, administrator = reviewer_app
    before = administrator.get("/api/profiles/hr").json()
    tool = administrator.get("/api/tools").json()[0]
    options = {
        "create-profile": ("POST", "/api/profiles", before),
        "update-profile": (
            "PUT",
            "/api/profiles/hr",
            {"expected_version": before["version"], "profile": before},
        ),
        "validate-profile": ("POST", "/api/profiles/validate", before),
        "import-profile": (
            "POST",
            "/api/profiles/import",
            {"schema_version": 1, "profile": before},
        ),
        "create-kb": (
            "POST",
            "/api/knowledge-bases",
            {"knowledge_base_id": "forbidden-kb", "name": "forbidden"},
        ),
        "save-tool": ("PUT", "/api/tools/" + tool["name"], tool),
        "import-openapi": ("POST", "/api/tools/import-openapi", {}),
        "create-prompt": (
            "POST",
            "/api/prompts",
            {"prompt_version_id": "forbidden-prompt", "content": "forbidden"},
        ),
        "create-account": (
            "POST",
            "/api/accounts",
            {"username": "forbidden", "password": PASSWORD, "role": "admin"},
        ),
        "update-account": (
            "PUT",
            "/api/accounts/" + accounts["reviewer"]["user_id"],
            {
                "expected_version": 1,
                "role": "admin",
                "profile_ids": ["hr"],
                "enabled": True,
            },
        ),
    }
    if operation == "upload":
        response = client.post(
            "/api/knowledge-bases/hr-kb/sources",
            files={"file": ("forbidden.txt", b"not imported", "text/plain")},
        )
    else:
        method, path, payload = options[operation]
        response = client.request(method, path, json=payload)
    assert response.status_code == 403, response.text
    assert administrator.get("/api/profiles/hr").json() == before
    assert client.get("/api/auth/me").json()["user"]["role"] == "reviewer"


def test_reviewer_chat_identity_stays_separate_from_other_accounts(reviewer_app):
    app, _, accounts, client, _ = reviewer_app
    member, _ = login(app, accounts["alice"])
    response = client.post("/api/sessions", json={"profile_id": "hr"})
    assert response.status_code == 201, response.text
    thread_id = response.json()["thread_id"]
    assert member.get(f"/api/sessions/{thread_id}").status_code == 404
    assert client.post("/api/sessions", json={"profile_id": "support"}).status_code == 403
    assert [s["thread_id"] for s in client.get("/api/sessions").json()] == [thread_id]


def test_profile_role_policy_can_revoke_reviewer_configuration_and_execution(reviewer_app):
    _, access, _, client, _ = reviewer_app
    with access.store.factory.begin() as db:
        row = db.get(AgentProfileRow, "hr")
        previous = dict(row.settings)
        row.settings = {**previous, "allowed_roles": ["admin"]}
    try:
        for path in ("profiles", "knowledge-bases", "tools", "prompts", "providers"):
            assert client.get("/api/" + path).json() == []
        assert client.get("/api/profiles/hr/export").status_code == 403
        assert client.get("/api/knowledge-bases/hr-kb/sources").status_code == 404
        assert client.post("/api/sessions", json={"profile_id": "hr"}).status_code == 403
    finally:
        with access.store.factory.begin() as db:
            db.get(AgentProfileRow, "hr").settings = previous
