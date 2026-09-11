"""Public-entry regression gates exercise actual cookies, identities and PostgreSQL races."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import sessionmaker

from omniagent.access import AccessService, AccountInput, AccountUpdate, fingerprint
from omniagent.access_config import AccessSettings
from omniagent.access_rows import AccountRow, LoginRow, QuotaRow, StreamLeaseRow
from omniagent.application import create_app
from omniagent.connectors import catalog
from omniagent.errors import PlatformError
from omniagent.identity import authenticate
from omniagent.presets import seed
from omniagent.session_rows import SessionRow

pytestmark = [pytest.mark.security, pytest.mark.integration]
ORIGIN = "https://studio.example"
PASSWORD = "integration-only-password-" + "a" * 16


@pytest.fixture
def public_app(monkeypatch):
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    monkeypatch.setenv("OMNIAGENT_ENV", "test")
    monkeypatch.setenv("OMNIAGENT_AUTH_MODE", "password")
    monkeypatch.setenv("OMNIAGENT_PUBLIC_ORIGIN", ORIGIN)
    app = create_app(url)
    access = app.state.access
    seed(app.state.store, catalog("127.0.0.1", 18081)[0])
    accounts = {}
    prefix = uuid4().hex[:12]
    for name, role in [("admin", "admin"), ("alice", "member"), ("bob", "member")]:
        accounts[name] = access.create_account(
            AccountInput(username=prefix + name, password=PASSWORD, role=role)
        )
    with access.store.factory.begin() as db:
        db.execute(delete(QuotaRow))
    yield app, access, accounts
    with access.store.factory.begin() as db:
        ids = [row["user_id"] for row in accounts.values()]
        db.execute(delete(SessionRow).where(SessionRow.user_id.in_(ids)))
        db.execute(delete(AccountRow).where(AccountRow.user_id.in_(ids)))
        db.execute(delete(QuotaRow))
        db.execute(delete(StreamLeaseRow))
    access.store.engine.dispose()


def login(app, account):
    client = TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})
    response = client.post(
        "/api/auth/login", json={"username": account["username"], "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client, response


def test_browser_login_is_unique_hashed_revocable_and_secure(public_app):
    app, access, accounts = public_app
    alice, response = login(app, accounts["alice"])
    bob, _ = login(app, accounts["bob"])
    cookie = response.headers["set-cookie"].lower()
    assert all(value in cookie for value in ("httponly", "secure", "samesite=strict", "path=/"))
    assert "domain=" not in cookie
    assert response.json()["user"]["user_id"] != bob.get("/api/auth/me").json()["user"]["user_id"]
    token = alice.cookies[access.settings.cookie_name]
    with access.store.factory() as db:
        assert db.get(LoginRow, token) is None
        assert db.get(LoginRow, fingerprint(token)) is not None
        assert db.get(AccountRow, accounts["alice"]["user_id"]).password_hash.startswith(
            "$argon2id$"
        )
    assert alice.post("/api/auth/logout").status_code == 204
    stolen = TestClient(app, base_url=ORIGIN, cookies={access.settings.cookie_name: token})
    assert stolen.get("/api/profiles").status_code == 401


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/profiles", "GET"),
        ("/api/accounts", "GET"),
        ("/api/sessions", "GET"),
        ("/api/telemetry", "GET"),
        ("/api/prompts", "GET"),
        ("/api/tools", "GET"),
    ],
)
def test_public_routes_reject_every_demo_token(public_app, path, method):
    app, _, _ = public_app
    client = TestClient(app, base_url=ORIGIN, headers={"Authorization": "Bearer local-demo-admin"})
    assert client.request(method, path).status_code == 401
    with pytest.raises(PlatformError):
        authenticate("Bearer local-demo-admin")


def test_same_role_users_cannot_read_mutate_or_stream_each_others_sessions(public_app):
    app, _, accounts = public_app
    alice, _ = login(app, accounts["alice"])
    bob, _ = login(app, accounts["bob"])
    thread = alice.post("/api/sessions", json={"profile_id": "hr"}).json()["thread_id"]
    assert bob.get("/api/sessions").json() == []
    for method, suffix in [
        ("GET", ""),
        ("DELETE", ""),
        ("POST", "/cancel"),
        ("POST", "/resume"),
        ("GET", "/events?follow=false"),
    ]:
        assert bob.request(method, "/api/sessions/" + thread + suffix).status_code == 404
    assert alice.get("/api/sessions/" + thread).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Origin": ""},
        {"X-CSRF-Token": "wrong"},
        {"X-CSRF-Token": ""},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_mutations_reject_cross_origin_and_missing_or_forged_csrf(public_app, headers):
    app, _, accounts = public_app
    client, _ = login(app, accounts["alice"])
    assert (
        client.post("/api/sessions", json={"profile_id": "hr"}, headers=headers).status_code == 403
    )
    assert client.get("/api/sessions").json() == []


def test_role_injection_and_account_update_revoke_old_sessions(public_app, monkeypatch):
    app, access, accounts = public_app
    alice, _ = login(app, accounts["alice"])
    assert alice.get("/api/accounts", headers={"X-Role": "admin"}).status_code == 403
    assert alice.get("/api/prompts").status_code == 403
    admin, _ = login(app, accounts["admin"])
    response = admin.put(
        "/api/accounts/" + accounts["alice"]["user_id"],
        json={"expected_version": 1, "enabled": False, "role": "member", "profile_ids": ["hr"]},
    )
    assert response.status_code == 200
    assert alice.get("/api/sessions").status_code == 401
    payload = AccountUpdate(expected_version=1, enabled=False, role="member", profile_ids=[])
    # A clean deployment already has its bootstrap admin. Arrange a sole admin inside
    # a rollback-only transaction, without changing any pre-existing account/device.
    with access.store.engine.connect() as connection:
        transaction = connection.begin()
        factory = sessionmaker(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            with factory.begin() as db:
                db.execute(
                    update(AccountRow)
                    .where(AccountRow.user_id != accounts["admin"]["user_id"])
                    .values(enabled=False)
                )
            with monkeypatch.context() as local:
                local.setattr(access.store, "factory", factory)
                with pytest.raises(PlatformError):
                    access.update_account(accounts["admin"]["user_id"], payload)
        finally:
            transaction.rollback()


def test_login_validation_expiry_rotation_and_generic_failure(public_app):
    app, access, accounts = public_app
    client, first = login(app, accounts["alice"])
    old = client.cookies[access.settings.cookie_name]
    second = client.post(
        "/api/auth/login", json={"username": accounts["alice"]["username"], "password": PASSWORD}
    )
    assert second.json()["csrf_token"] != first.json()["csrf_token"]
    with pytest.raises(PlatformError):
        access.actor(old)
    for username in [accounts["alice"]["username"], "missing-user"]:
        result = client.post("/api/auth/login", json={"username": username, "password": "wrong"})
        assert result.status_code == 401
        assert result.json()["error"]["message"] == "Invalid credentials"
    assert (
        client.post(
            "/api/auth/login", json={"username": "test", "password": PASSWORD, "role": "admin"}
        ).status_code
        == 422
    )
    with access.store.factory.begin() as db:
        row = db.get(LoginRow, fingerprint(client.cookies[access.settings.cookie_name]))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert client.get("/api/auth/me").status_code == 401


def test_quotas_are_atomic_across_workers_and_restart(public_app):
    _, access, _ = public_app
    instances = [AccessService(access.store, access.settings) for _ in range(2)]

    def attempt(index):
        try:
            instances[index % 2].reserve([("concurrent", 1, 7)])
            return True
        except PlatformError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 7
    with pytest.raises(PlatformError):
        AccessService(access.store, access.settings).reserve([("concurrent", 1, 7)])
    with access.store.factory() as db:
        assert db.scalar(select(QuotaRow.used).where(QuotaRow.used == 7)) == 7


def test_password_rotation_revokes_every_device_and_rejects_old_password(public_app):
    app, _, accounts = public_app
    first, _ = login(app, accounts["alice"])
    second, _ = login(app, accounts["alice"])
    new_password = "rotated-private-fixture-" + uuid4().hex
    assert (
        first.post(
            "/api/auth/password", json={"current_password": "wrong", "new_password": new_password}
        ).status_code
        == 403
    )
    assert first.get("/api/auth/me").status_code == 200
    assert (
        first.post(
            "/api/auth/password", json={"current_password": PASSWORD, "new_password": new_password}
        ).status_code
        == 204
    )
    assert second.get("/api/profiles").status_code == 401
    assert first.get("/api/profiles").status_code == 401
    assert (
        first.post(
            "/api/auth/login",
            json={"username": accounts["alice"]["username"], "password": PASSWORD},
        ).status_code
        == 401
    )
    assert (
        first.post(
            "/api/auth/login",
            json={"username": accounts["alice"]["username"], "password": new_password},
        ).status_code
        == 200
    )


def test_model_call_token_and_stream_limits_fail_closed(public_app):
    app, access, accounts = public_app
    client, _ = login(app, accounts["alice"])
    actor = access.actor(client.cookies[access.settings.cookie_name])
    access.settings = replace(access.settings, user_daily_calls=2, user_daily_tokens=12)
    access.reserve_model(actor, 6)
    access.reserve_model(actor, 6)
    with pytest.raises(PlatformError):
        access.reserve_model(actor, 1)
    leases = [access.open_stream(actor) for _ in range(3)]
    with pytest.raises(PlatformError):
        AccessService(access.store, access.settings).open_stream(actor)
    access.close_stream(leases.pop())
    assert access.open_stream(actor)


@pytest.mark.parametrize(
    "environment,mode,origin,password",
    [
        ("production", "dev", ORIGIN, "a" * 32),
        ("production", "password", "http://studio.example", "a" * 32),
        ("production", "password", ORIGIN, "local-demo"),
        ("local", "password", ORIGIN, "a" * 32),
        ("production", "password", ORIGIN + "/path", "a" * 32),
    ],
)
def test_insecure_deployment_configuration_cannot_start(
    monkeypatch, environment, mode, origin, password
):
    monkeypatch.setenv("OMNIAGENT_ENV", environment)
    monkeypatch.setenv("OMNIAGENT_AUTH_MODE", mode)
    monkeypatch.setenv("OMNIAGENT_PUBLIC_ORIGIN", origin)
    with pytest.raises(ValueError):
        AccessSettings.from_environment(f"postgresql+psycopg://runtime:{password}@db/app")


def test_legacy_api_cannot_be_used_as_an_unauthenticated_entrypoint(monkeypatch):
    from omniagent.api import app

    monkeypatch.setenv("OMNIAGENT_ENV", "production")
    monkeypatch.setenv("OMNIAGENT_AUTH_MODE", "password")
    client = TestClient(app)
    assert client.get("/agent-profiles").status_code == 410
    assert client.get("/openapi.json").status_code == 410
