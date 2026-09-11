import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from omniagent.access import PASSWORDS, fingerprint
from omniagent.access_rows import AccountRow, LoginRow
from omniagent.account_cli import manage_account
from omniagent.audit import hashed
from omniagent.database import build_engine
from omniagent.session_rows import AuditRow
from omniagent.session_store import SessionStore

pytestmark = [pytest.mark.integration, pytest.mark.security]


@pytest.fixture
def account(monkeypatch):
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    monkeypatch.setenv("OMNIAGENT_ENV", "test")
    monkeypatch.setenv("OMNIAGENT_AUTH_MODE", "password")
    monkeypatch.setenv("OMNIAGENT_PUBLIC_ORIGIN", "http://127.0.0.1:8080")
    store = SessionStore(build_engine(url))
    user_id = uuid4().hex
    username = "cli-audit-" + user_id
    old_hash = PASSWORDS.hash(secrets.token_urlsafe(24))
    new_password = secrets.token_urlsafe(24)
    login_ids = [fingerprint(secrets.token_urlsafe(32)) for _ in range(2)]
    expiry = datetime.now(UTC) + timedelta(hours=1)
    with store.factory.begin() as db:
        db.add(
            AccountRow(
                user_id=user_id,
                username=username,
                password_hash=old_hash,
                role="member",
                profile_ids=[],
                enabled=True,
                version=7,
            )
        )
        db.flush()
        db.add_all(
            LoginRow(token_hash=identifier, user_id=user_id, expires_at=expiry)
            for identifier in login_ids
        )
    yield SimpleNamespace(
        store=store,
        url=url,
        user_id=user_id,
        username=username,
        old_hash=old_hash,
        new_password=new_password,
        login_ids=login_ids,
        expiry=expiry,
    )
    with store.factory.begin() as db:
        db.execute(delete(AccountRow).where(AccountRow.user_id == user_id))
        db.execute(
            delete(AuditRow).where(AuditRow.details["object_hash"].astext == hashed(user_id))
        )
    store.engine.dispose()


def test_password_rotation_rolls_back_password_version_and_logins_when_audit_fails(
    account, monkeypatch, capsys
):
    s = account
    raw = json.dumps({"username": s.username, "password": s.new_password})
    audit_attempts = []

    def audit_unavailable(db, *args, **kwargs):
        db.flush()
        changed = db.get(AccountRow, s.user_id)
        assert changed.version == 8
        assert PASSWORDS.verify(changed.password_hash, s.new_password)
        assert db.scalar(select(LoginRow).where(LoginRow.user_id == s.user_id)) is None
        audit_attempts.append(s.user_id)
        raise RuntimeError("injected audit failure after flushed account changes")

    with monkeypatch.context() as patch:
        patch.setattr("omniagent.account_cli.audit_change", audit_unavailable)
        with pytest.raises(SystemExit, match="Account operation failed"):
            manage_account("account-password", s.url, raw)
    assert audit_attempts == [s.user_id]
    assert capsys.readouterr().out == ""
    with s.store.factory() as db:
        unchanged = db.get(AccountRow, s.user_id)
        assert unchanged.password_hash == s.old_hash
        assert unchanged.version == 7
        logins = list(db.scalars(select(LoginRow).where(LoginRow.user_id == s.user_id)))
        assert {login.token_hash for login in logins} == set(s.login_ids)
        assert all(login.expires_at == s.expiry for login in logins)
        assert (
            db.scalar(
                select(AuditRow).where(AuditRow.details["object_hash"].astext == hashed(s.user_id))
            )
            is None
        )

    manage_account("account-password", s.url, raw)
    assert json.loads(capsys.readouterr().out) == {"account": s.username, "password_rotated": True}
    with s.store.factory() as db:
        changed = db.get(AccountRow, s.user_id)
        assert changed.version == 8
        assert PASSWORDS.verify(changed.password_hash, s.new_password)
        assert db.scalar(select(LoginRow).where(LoginRow.user_id == s.user_id)) is None
        audits = list(
            db.scalars(
                select(AuditRow).where(AuditRow.details["object_hash"].astext == hashed(s.user_id))
            )
        )
        assert len(audits) == 1
        audit = audits[0]
        assert audit.action == "account.password_rotated"
        assert audit.actor_hash == hashed("local-operator")
        assert audit.details["before_version"] == 7
        assert audit.details["after_version"] == 8
        assert s.new_password not in json.dumps(audit.details)
        assert s.old_hash not in json.dumps(audit.details)
        assert changed.password_hash not in json.dumps(audit.details)
