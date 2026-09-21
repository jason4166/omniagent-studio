"""Daily token settlement is durable, atomic and independent of run/attempt budgets."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from omniagent.access import PUBLIC_PASSWORD, PUBLIC_USERNAME, AccessService, fingerprint
from omniagent.access_config import AccessSettings
from omniagent.access_rows import AccountRow, ModelQuotaReservationRow, QuotaRow
from omniagent.application import create_app
from omniagent.connectors import catalog
from omniagent.database import build_engine
from omniagent.errors import ErrorCode, PlatformError
from omniagent.identity import DevUserContext
from omniagent.llm import FakeLLM, LLMResponse, LLMUsage
from omniagent.maintenance import purge
from omniagent.presets import seed
from omniagent.session_store import SessionStore

pytestmark = [pytest.mark.integration, pytest.mark.security]


@pytest.fixture
def quota_access(monkeypatch):
    url = os.environ.get("OMNIAGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OMNIAGENT_TEST_DATABASE_URL required")
    monkeypatch.setenv("OMNIAGENT_ENV", "test")
    monkeypatch.setenv("OMNIAGENT_AUTH_MODE", "password")
    monkeypatch.setenv("OMNIAGENT_PUBLIC_ORIGIN", "https://studio.example")
    monkeypatch.setenv("OMNIAGENT_PUBLIC_PREVIEW_ENABLED", "true")
    store = SessionStore(build_engine(url))
    access = AccessService(store, AccessSettings.from_environment(url))
    actor = DevUserContext(
        user_id="quota-" + uuid4().hex,
        role="reviewer",
        profile_ids=access.settings.public_preview_profile_ids,
        is_public_guest=True,
    )
    with store.factory.begin() as db:
        db.execute(delete(ModelQuotaReservationRow))
        db.execute(delete(QuotaRow))
        db.add(
            AccountRow(
                user_id=actor.user_id,
                username=actor.user_id,
                password_hash="!no-password-login",  # noqa: S106 - password login is disabled
                role=actor.role,
                profile_ids=list(actor.profile_ids),
                enabled=True,
                version=1,
                expires_at=datetime.now(UTC) + timedelta(days=2),
            )
        )
    yield access, actor, url
    with store.factory.begin() as db:
        db.execute(delete(ModelQuotaReservationRow))
        db.execute(delete(QuotaRow))
        db.execute(delete(AccountRow).where(AccountRow.user_id == actor.user_id))
    store.engine.dispose()


def usage(tokens):
    return LLMUsage(input_tokens=tokens, output_tokens=0, total_tokens=tokens)


def bucket_used(access, name, now=None):
    bucket = int((now or datetime.now(UTC)).timestamp()) // 86400
    with access.store.factory() as db:
        row = db.get(QuotaRow, fingerprint(f"{name}:86400:{bucket}"))
        return row.used if row else 0


def assert_usage(access, actor, tokens, calls):
    for suffix in ("global", actor.user_id, "public-preview"):
        assert bucket_used(access, "tokens:" + suffix) == tokens
        assert bucket_used(access, "model:" + suffix) == calls


def test_known_usage_settles_all_token_windows_once_across_restart(quota_access):
    access, actor, _ = quota_access
    receipt = access.reserve_model(actor, 100)
    assert receipt
    assert_usage(access, actor, 100, 1)
    restarted = AccessService(access.store, access.settings)
    restarted.settle_model(actor, receipt, usage(17))
    access.settle_model(actor, receipt, usage(17))
    assert_usage(access, actor, 17, 1)
    with pytest.raises(PlatformError) as conflict:
        access.settle_model(actor, receipt, usage(1))
    assert conflict.value.code == ErrorCode.CONFLICT
    assert_usage(access, actor, 17, 1)


def test_unknown_or_invalid_usage_keeps_the_full_reservation(quota_access):
    access, actor, _ = quota_access
    receipt = access.reserve_model(actor, 100)
    access.settle_model(actor, receipt, None)
    with pytest.raises(PlatformError) as invalid:
        access.settle_model(
            actor, receipt, LLMUsage(input_tokens=1, output_tokens=1, total_tokens=0)
        )
    assert invalid.value.code == ErrorCode.BAD_RESPONSE
    assert_usage(access, actor, 100, 1)
    # An unknown failed attempt remains charged when a separate retry reports known usage.
    retried = access.reserve_model(actor, 100)
    access.settle_model(actor, retried, usage(17))
    assert_usage(access, actor, 117, 2)


@pytest.mark.parametrize(
    "limited", ["user_daily_tokens", "global_daily_tokens", "public_preview_daily_tokens"]
)
def test_rejected_reservation_rolls_back_all_windows_and_its_receipt(quota_access, limited):
    access, actor, _ = quota_access
    access.settings = replace(access.settings, **{limited: 150})
    access.reserve_model(actor, 100)
    with pytest.raises(PlatformError) as denied:
        access.reserve_model(actor, 100)
    assert denied.value.code == ErrorCode.DAILY_QUOTA
    assert_usage(access, actor, 100, 1)
    with access.store.factory() as db:
        assert len(list(db.scalars(select(ModelQuotaReservationRow)))) == 1


def test_actual_overrun_is_committed_before_rejection_and_is_idempotent(quota_access):
    access, actor, _ = quota_access
    access.settings = replace(access.settings, public_preview_daily_tokens=120)
    receipt = access.reserve_model(actor, 100)
    for _ in range(2):
        with pytest.raises(PlatformError) as exhausted:
            access.settle_model(actor, receipt, usage(150))
        assert exhausted.value.code == ErrorCode.DAILY_QUOTA
        assert_usage(access, actor, 150, 1)
    with pytest.raises(PlatformError) as denied:
        access.reserve_model(actor, 1)
    assert denied.value.code == ErrorCode.DAILY_QUOTA
    assert_usage(access, actor, 150, 1)


def test_concurrent_reservations_and_duplicate_settlements_do_not_oversell(quota_access):
    access, actor, _ = quota_access
    access.settings = replace(access.settings, public_preview_daily_tokens=700)
    workers = [AccessService(access.store, access.settings) for _ in range(2)]

    def reserve(index):
        try:
            return workers[index % 2].reserve_model(actor, 100)
        except PlatformError as error:
            assert error.code == ErrorCode.DAILY_QUOTA
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = [receipt for receipt in pool.map(reserve, range(20)) if receipt]
    assert len(receipts) == 7
    assert_usage(access, actor, 700, 7)

    def settle(index):
        workers[index % 2].settle_model(actor, receipts[index % 7], usage(10))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(settle, range(28)))
    assert_usage(access, actor, 70, 7)


def test_interleaved_reservation_and_settlement_preserve_all_in_flight_allowances(quota_access):
    access, actor, _ = quota_access
    access.settings = replace(access.settings, public_preview_daily_tokens=800)
    receipts = [access.reserve_model(actor, 100) for _ in range(4)]
    workers = [AccessService(access.store, access.settings) for _ in range(2)]

    def work(index):
        worker = workers[index % 2]
        if index % 2:
            worker.settle_model(actor, receipts[(index // 2) % 4], usage(10))
        else:
            try:
                worker.reserve_model(actor, 100)
            except PlatformError as error:
                assert error.code == ErrorCode.DAILY_QUOTA

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, range(32)))
    with access.store.factory() as db:
        rows = list(db.scalars(select(ModelQuotaReservationRow)))
    expected = sum(
        row.actual_tokens if row.actual_tokens is not None else row.reserved_tokens for row in rows
    )
    assert expected <= 800
    assert_usage(access, actor, expected, len(rows))


def test_missing_original_window_rolls_back_the_entire_settlement(quota_access):
    access, actor, _ = quota_access
    receipt = access.reserve_model(actor, 100)
    with access.store.factory.begin() as db:
        keys = sorted(db.get(ModelQuotaReservationRow, receipt).token_windows)
        db.execute(delete(QuotaRow).where(QuotaRow.key == keys[-1]))
    with pytest.raises(PlatformError) as unavailable:
        access.settle_model(actor, receipt, usage(17))
    assert unavailable.value.code == ErrorCode.UNAVAILABLE
    with access.store.factory() as db:
        assert db.get(ModelQuotaReservationRow, receipt).actual_tokens is None
        assert all(db.get(QuotaRow, key).used == 100 for key in keys[:-1])


def test_settlement_cannot_refund_another_user_and_survives_owner_revocation(quota_access):
    access, actor, _ = quota_access
    receipt = access.reserve_model(actor, 100)
    with pytest.raises(PlatformError) as forbidden:
        access.settle_model(actor.model_copy(update={"user_id": "another-user"}), receipt, usage(1))
    assert forbidden.value.code == ErrorCode.PERMISSION
    with access.store.factory.begin() as db:
        db.get(AccountRow, actor.user_id).enabled = False
    access.settle_model(actor, receipt, usage(17))
    assert_usage(access, actor, 17, 1)
    with pytest.raises(PlatformError) as revoked:
        access.reserve_model(actor, 100)
    assert revoked.value.code == ErrorCode.AUTH


def test_midnight_settlement_targets_original_windows_only(quota_access, monkeypatch):
    access, actor, _ = quota_access
    before = datetime.now(UTC).replace(hour=23, minute=59, second=59, microsecond=0)

    class Clock(datetime):
        current = before

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr("omniagent.access.datetime", Clock)
    receipt = access.reserve_model(actor, 100)
    Clock.current = before + timedelta(seconds=2)
    access.reserve_model(actor, 50)
    access.settle_model(actor, receipt, usage(17))
    for suffix in ("global", actor.user_id, "public-preview"):
        assert bucket_used(access, "tokens:" + suffix, before) == 17
        assert bucket_used(access, "tokens:" + suffix, Clock.current) == 50
        assert bucket_used(access, "model:" + suffix, before) == 1
        assert bucket_used(access, "model:" + suffix, Clock.current) == 1


def test_expired_receipts_do_not_refund_and_retention_cleans_them(quota_access):
    access, actor, url = quota_access
    receipt = access.reserve_model(actor, 100)
    with access.store.factory.begin() as db:
        row = db.get(ModelQuotaReservationRow, receipt)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        keys = list(row.token_windows)
        for key in keys:
            db.get(QuotaRow, key).expires_at = row.expires_at
    with pytest.raises(PlatformError) as expired:
        access.settle_model(actor, receipt, usage(17))
    assert expired.value.code == ErrorCode.EXPIRED
    assert_usage(access, actor, 100, 1)
    purge(url)
    with access.store.factory() as db:
        assert db.get(ModelQuotaReservationRow, receipt) is None
        assert all(db.get(QuotaRow, key) is None for key in keys)
    with pytest.raises(PlatformError) as absent:
        access.settle_model(actor, receipt, usage(17))
    assert absent.value.code == ErrorCode.NOT_FOUND


def test_public_application_records_actual_daily_tokens_and_preserves_run_reservation(quota_access):
    access, _, url = quota_access
    provider = FakeLLM(
        LLMResponse(
            model="fake-v1",
            content='{"route":"clarify","reason":"Missing request","confidence":1,'
            '"output_text":"请说明需要帮助的问题。"}',
            usage=usage(17),
        )
    )
    app = create_app(url, provider=provider)
    seed(app.state.store, catalog("127.0.0.1", 18081)[0])
    with TestClient(
        app, base_url="https://studio.example", headers={"Origin": "https://studio.example"}
    ) as client:
        logged_in = client.post(
            "/api/auth/login", json={"username": PUBLIC_USERNAME, "password": PUBLIC_PASSWORD}
        )
        assert logged_in.status_code == 200
        actor = DevUserContext.model_validate(logged_in.json()["user"])
        client.headers["X-CSRF-Token"] = logged_in.json()["csrf_token"]
        created = client.post("/api/sessions", json={"profile_id": "hr"})
        assert created.status_code == 201
        thread = created.json()["thread_id"]
        try:
            response = client.post(
                f"/api/sessions/{thread}/messages",
                json={"message": "Help me", "request_key": "public-usage-settlement"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "completed"
            assert response.json()["usage"]["reserved_tokens"] > 17
            assert response.json()["usage"]["total_tokens"] == 17
            assert_usage(access, actor, 17, 1)
        finally:
            assert client.delete(f"/api/sessions/{thread}").status_code == 204
            assert client.post("/api/auth/logout").status_code == 204
            with access.store.factory.begin() as db:
                db.execute(delete(AccountRow).where(AccountRow.user_id == actor.user_id))
