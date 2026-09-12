"""Public reviewer entry preserves isolation, revocation and shared spending limits."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select

from omniagent.access import (
    PUBLIC_PASSWORD,
    PUBLIC_USERNAME,
    AccessService,
    AccountInput,
    AccountUpdate,
    LoginInput,
    PasswordChange,
    fingerprint,
)
from omniagent.access_config import AccessSettings
from omniagent.access_rows import AccountRow, LoginRow, QuotaRow, StreamLeaseRow
from omniagent.application import create_app
from omniagent.connectors import catalog
from omniagent.errors import ErrorCode, PlatformError
from omniagent.identity import DevUserContext
from omniagent.maintenance import purge
from omniagent.postgres_repositories import SqlAlchemyAgentProfileRepository
from omniagent.presets import seed
from omniagent.session_rows import SessionRow

pytestmark = [pytest.mark.security, pytest.mark.integration]
ORIGIN = "https://studio.example"
PUBLIC_LOGIN = {"username": PUBLIC_USERNAME, "password": PUBLIC_PASSWORD}
PRIVATE_PASSWORD = "fixture-only-password-" + "b" * 16


@pytest.fixture
def preview(monkeypatch):
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    monkeypatch.setenv("OMNIAGENT_ENV", "test")
    monkeypatch.setenv("OMNIAGENT_AUTH_MODE", "password")
    monkeypatch.setenv("OMNIAGENT_PUBLIC_ORIGIN", ORIGIN)
    monkeypatch.setenv("OMNIAGENT_PUBLIC_PREVIEW_ENABLED", "true")
    monkeypatch.setenv("OMNIAGENT_PUBLIC_PREVIEW_PROFILE_IDS", "hr,support,sales")
    app = create_app(url)
    access = app.state.access
    seed(app.state.store, catalog("127.0.0.1", 18081)[0])
    with access.store.factory.begin() as db:
        original_ids = set(db.scalars(select(AccountRow.user_id)))
        db.execute(delete(QuotaRow))
    admin = access.create_account(
        AccountInput(
            username="preview-admin-" + uuid4().hex[:12], password=PRIVATE_PASSWORD, role="admin"
        )
    )
    yield app, access, admin, SecretStr(url)
    with access.store.factory.begin() as db:
        ids = set(db.scalars(select(AccountRow.user_id))) - original_ids
        db.execute(delete(SessionRow).where(SessionRow.user_id.in_(ids)))
        db.execute(delete(AccountRow).where(AccountRow.user_id.in_(ids)))
        db.execute(delete(StreamLeaseRow).where(StreamLeaseRow.user_id.in_(ids)))
        db.execute(delete(QuotaRow))
    access.store.engine.dispose()


def public_client(app):
    client = TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    response = client.post("/api/auth/login", json=PUBLIC_LOGIN)
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client, response.json()["user"]


def test_login_options_are_public_explicit_and_never_expose_real_credentials(preview):
    app, access, admin, _ = preview
    client = TestClient(app, base_url=ORIGIN)
    result = client.get("/api/auth/options")
    assert result.status_code == 200
    assert result.json() == {"public_login": PUBLIC_LOGIN}
    assert "no-store" in result.headers["cache-control"]
    assert PRIVATE_PASSWORD not in result.text and admin["username"] not in result.text
    access.settings = replace(access.settings, public_preview_enabled=False)
    assert client.get("/api/auth/options").json() == {"public_login": None}
    assert (
        client.post("/api/auth/login", headers={"Origin": ORIGIN}, json=PUBLIC_LOGIN).status_code
        == 401
    )
    # Disabling public entry does not disable independent password accounts.
    assert (
        client.post(
            "/api/auth/login",
            headers={"Origin": ORIGIN},
            json={"username": admin["username"], "password": PRIVATE_PASSWORD},
        ).status_code
        == 200
    )


def test_public_logins_have_isolated_durable_identities_and_secure_cookies(preview):
    app, access, _, _ = preview
    alice, user = public_client(app)
    bob, other = public_client(app)
    assert user["role"] == "reviewer" and user["is_public_guest"] is True
    assert user["user_id"] != other["user_id"]
    token = alice.cookies[access.settings.cookie_name]
    actor = AccessService(access.store, access.settings).actor(token)
    assert actor.user_id == user["user_id"] and actor.permission_role == "member"
    alice_thread = alice.post("/api/sessions", json={"profile_id": "hr"})
    assert alice_thread.status_code == 201, alice_thread.text
    identifier = alice_thread.json()["thread_id"]
    assert bob.get("/api/sessions").json() == []
    for method, suffix in [
        ("GET", ""),
        ("DELETE", ""),
        ("POST", "/cancel"),
        ("POST", "/resume"),
        ("GET", "/events?follow=false"),
    ]:
        assert bob.request(method, "/api/sessions/" + identifier + suffix).status_code == 404
    with access.store.factory() as db:
        account = db.get(AccountRow, actor.user_id)
        assert account.expires_at is not None
        assert account.password_hash.startswith("!")
        assert db.get(LoginRow, token) is None
        assert db.get(LoginRow, fingerprint(token)) is not None
    response = alice.post("/api/auth/login", json=PUBLIC_LOGIN)
    assert response.json()["user"] == user
    assert alice.cookies[access.settings.cookie_name] != token
    assert alice.get("/api/sessions").json()[0]["thread_id"] == identifier
    assert all(
        flag in response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=strict", "path=/")
    )
    with pytest.raises(PlatformError):
        access.actor(token)


@pytest.mark.parametrize("change", ["disable", "expire", "profiles", "role", "account"])
def test_public_access_revalidates_policy_expiry_and_role_for_existing_sessions(preview, change):
    app, access, _, _ = preview
    client, user = public_client(app)
    actor = access.actor(client.cookies[access.settings.cookie_name])
    if change == "disable":
        access.settings = replace(access.settings, public_preview_enabled=False)
    elif change == "profiles":
        access.settings = replace(access.settings, public_preview_profile_ids=("hr",))
    else:
        with access.store.factory.begin() as db:
            row = db.get(AccountRow, user["user_id"])
            if change == "expire":
                row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            elif change == "role":
                row.role = "admin"
            else:
                row.enabled = False
    assert client.get("/api/auth/me").status_code == 401
    with pytest.raises(PlatformError) as denied:
        AccessService(access.store, access.settings).reserve_model(actor, 1)
    assert denied.value.code == ErrorCode.AUTH


def test_public_password_names_and_permission_mutations_are_not_supported(preview):
    app, access, admin, _ = preview
    client, user = public_client(app)
    change = {"current_password": PUBLIC_PASSWORD, "new_password": PRIVATE_PASSWORD}
    assert client.post("/api/auth/password", json=change).status_code == 403
    assert (
        client.post(
            "/api/accounts",
            json={"username": "inject", "password": PRIVATE_PASSWORD, "role": "admin"},
        ).status_code
        == 403
    )
    assert client.get("/api/accounts").status_code == 403
    actor = access.actor(client.cookies[access.settings.cookie_name])
    with pytest.raises(PlatformError):
        access.change_password(
            actor.model_copy(update={"is_public_guest": False}), PasswordChange(**change)
        )
    with pytest.raises(PlatformError):
        access.update_account(
            user["user_id"],
            AccountUpdate(expected_version=1, enabled=True, role="admin", profile_ids=["hr"]),
            actor_id=admin["user_id"],
        )
    for username in [PUBLIC_USERNAME, "guest-" + uuid4().hex]:
        with pytest.raises(PlatformError):
            access.create_account(AccountInput(username=username, password=PRIVATE_PASSWORD))
    with access.store.factory() as db:
        username = db.get(AccountRow, user["user_id"]).username
    assert (
        client.post(
            "/api/auth/login", json={"username": username, "password": PUBLIC_PASSWORD}
        ).status_code
        == 401
    )
    administrator = TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    result = administrator.post(
        "/api/auth/login", json={"username": admin["username"], "password": PRIVATE_PASSWORD}
    )
    assert result.status_code == 200
    rows = administrator.get("/api/accounts").json()
    assert user["user_id"] not in {row["user_id"] for row in rows}
    assert admin["user_id"] in {row["user_id"] for row in rows}


def test_public_login_rejects_schema_injection_and_cross_origin_requests(preview):
    app, _, _, _ = preview
    client = TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    for field, value in [
        ("role", "admin"),
        ("profile_ids", ["private"]),
        ("is_public_guest", False),
    ]:
        assert (
            client.post("/api/auth/login", json={**PUBLIC_LOGIN, field: value}).status_code == 422
        )
    for headers in [
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
    ]:
        assert client.post("/api/auth/login", json=PUBLIC_LOGIN, headers=headers).status_code == 403
    assert (
        client.post("/api/auth/login", json={**PUBLIC_LOGIN, "password": "wrong"}).status_code
        == 401
    )
    client, _ = public_client(app)
    assert (
        client.post(
            "/api/sessions", json={"profile_id": "hr"}, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )


def test_repeated_public_login_cannot_extend_identity_lifetime(preview):
    app, access, _, _ = preview
    client, user = public_client(app)
    with access.store.factory.begin() as db:
        row = db.get(AccountRow, user["user_id"])
        deadline = datetime.now(UTC) + timedelta(seconds=30)
        row.expires_at = deadline
    result = client.post("/api/auth/login", json=PUBLIC_LOGIN)
    assert result.status_code == 200 and result.json()["user"] == user
    with access.store.factory() as db:
        assert db.get(AccountRow, user["user_id"]).expires_at == deadline
        token = client.cookies[access.settings.cookie_name]
        assert db.get(LoginRow, fingerprint(token)).expires_at == deadline


def test_public_login_quota_is_shared_across_workers_and_restarts(preview):
    _, access, _, _ = preview
    settings = replace(access.settings, public_preview_daily_logins=5)
    workers = [AccessService(access.store, settings) for _ in range(2)]

    def attempt(index):
        try:
            workers[index % 2].login(LoginInput(**PUBLIC_LOGIN))
            return True
        except PlatformError as error:
            assert error.code == ErrorCode.RATE_LIMIT
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(12))) == 5
    with pytest.raises(PlatformError) as exhausted:
        AccessService(access.store, settings).login(LoginInput(**PUBLIC_LOGIN))
    assert exhausted.value.code == ErrorCode.RATE_LIMIT


@pytest.mark.parametrize(
    "limited_setting", ["public_preview_daily_calls", "public_preview_daily_tokens"]
)
def test_new_public_identities_cannot_bypass_shared_model_budget(preview, limited_setting):
    app, access, _, _ = preview
    access.settings = replace(access.settings, **{limited_setting: 2})
    for _ in range(2):
        client, _ = public_client(app)
        actor = access.actor(client.cookies[access.settings.cookie_name])
        access.reserve_model(actor, 1)
    client, _ = public_client(app)
    actor = access.actor(client.cookies[access.settings.cookie_name])
    with pytest.raises(PlatformError) as exhausted:
        AccessService(access.store, access.settings).reserve_model(actor, 1)
    assert exhausted.value.code == ErrorCode.RATE_LIMIT


def test_retention_removes_expired_public_data_and_preserves_permanent_accounts(preview):
    app, access, admin, url = preview
    client, user = public_client(app)
    identifier = client.post("/api/sessions", json={"profile_id": "hr"}).json()["thread_id"]
    with access.store.factory.begin() as db:
        db.get(AccountRow, user["user_id"]).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    result = purge(url.get_secret_value())
    assert result["expired_public_accounts_deleted"] == 1
    assert result["expired_sessions_deleted"] >= 1
    with access.store.factory() as db:
        assert db.get(AccountRow, user["user_id"]) is None
        assert db.get(SessionRow, identifier) is None
        assert db.get(AccountRow, admin["user_id"]).enabled


@pytest.mark.parametrize(
    "setting,value",
    [
        ("OMNIAGENT_PUBLIC_PREVIEW_ENABLED", "yes"),
        ("OMNIAGENT_PUBLIC_PREVIEW_PROFILE_IDS", ""),
        ("OMNIAGENT_PUBLIC_PREVIEW_PROFILE_IDS", "hr,hr"),
        ("OMNIAGENT_PUBLIC_PREVIEW_PROFILE_IDS", "hr,*"),
        ("OMNIAGENT_PUBLIC_PREVIEW_TTL_SECONDS", "86401"),
        ("OMNIAGENT_PUBLIC_PREVIEW_DAILY_LOGINS", "0"),
        ("OMNIAGENT_PUBLIC_PREVIEW_DAILY_MODEL_CALLS", "-1"),
        ("OMNIAGENT_PUBLIC_PREVIEW_DAILY_TOKENS", "10000001"),
    ],
)
def test_public_preview_configuration_fails_closed(monkeypatch, setting, value):
    monkeypatch.setenv("OMNIAGENT_ENV", "test")
    monkeypatch.setenv("OMNIAGENT_AUTH_MODE", "password")
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError):
        AccessSettings.from_environment("postgresql+psycopg://localhost/app")


def test_reviewer_permissions_require_an_explicit_profile_allowlist(preview):
    app, _, _, _ = preview
    profiles = app.state.store
    with profiles.factory() as db:
        profile = SqlAlchemyAgentProfileRepository(db).get("hr")
    actor = DevUserContext(user_id="reviewer", role="reviewer", profile_ids=("hr",))
    actor.authorize_profile(profile)
    with pytest.raises(PlatformError):
        actor.model_copy(update={"profile_ids": ()}).authorize_profile(profile)
