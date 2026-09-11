"""Password authentication, database-backed quotas and server-owned account permissions."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from omniagent.access_config import AccessSettings
from omniagent.access_rows import AccountRow, LoginRow, QuotaRow, StreamLeaseRow
from omniagent.errors import ErrorCode, PlatformError
from omniagent.identity import DevUserContext
from omniagent.session_rows import AuditRow
from omniagent.session_store import SessionStore
from omniagent.telemetry import trace_metadata

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
ProfileId = Annotated[str, Field(min_length=1, max_length=120)]


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: SecretStr = Field(min_length=1, max_length=256)


class AccountInput(LoginInput):
    password: SecretStr = Field(min_length=15, max_length=256)
    role: Literal["admin", "member", "viewer"] = "member"
    profile_ids: list[ProfileId] = Field(
        default_factory=lambda: ["hr", "support", "sales"], max_length=30
    )


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    enabled: bool
    role: Literal["admin", "member", "viewer"]
    profile_ids: list[ProfileId] = Field(max_length=30)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=15, max_length=256)


def account_view(row: AccountRow) -> dict[str, object]:
    return {
        "user_id": row.user_id,
        "username": row.username,
        "role": row.role,
        "profile_ids": row.profile_ids,
        "enabled": row.enabled,
        "version": row.version,
    }


class AccessService:
    def __init__(self, store: SessionStore, settings: AccessSettings) -> None:
        self.store = store
        self.settings = settings

    def audit(self, actor_id: str, action: str, target_id: str = "") -> None:
        with self.store.factory.begin() as db:
            db.add(
                AuditRow(
                    audit_id=str(uuid4()),
                    actor_hash=fingerprint(actor_id),
                    thread_id="",
                    run_id=None,
                    action=action,
                    details={"target_hash": fingerprint(target_id), **trace_metadata()},
                    created_at=datetime.now(UTC),
                )
            )

    def open_stream(self, actor: DevUserContext) -> str:
        now = datetime.now(UTC)
        lease_id = str(uuid4())
        with self.store.factory.begin() as db:
            lock = int.from_bytes(hashlib.sha256(actor.user_id.encode()).digest()[:8], signed=True)
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
            active = list(
                db.scalars(
                    select(StreamLeaseRow.lease_id).where(
                        StreamLeaseRow.user_id == actor.user_id, StreamLeaseRow.expires_at > now
                    )
                )
            )
            if len(active) >= 3:
                raise PlatformError(ErrorCode.RATE_LIMIT, "Too many active streams")
            db.add(
                StreamLeaseRow(
                    lease_id=lease_id, user_id=actor.user_id, expires_at=now + timedelta(seconds=90)
                )
            )
        return lease_id

    def close_stream(self, lease_id: str) -> None:
        with self.store.factory.begin() as db:
            db.execute(delete(StreamLeaseRow).where(StreamLeaseRow.lease_id == lease_id))

    def reserve(self, reservations: list[tuple[str, int, int]], seconds: int = 86400) -> None:
        """One transaction reserves every limit before work; failures never refund attempts."""
        now = datetime.now(UTC)
        bucket = int(now.timestamp()) // seconds
        with self.store.factory.begin() as db:
            for key, amount, limit in sorted(reservations):
                if amount < 1 or amount > limit:
                    raise PlatformError(ErrorCode.RATE_LIMIT, "Request allowance exhausted")
                statement = insert(QuotaRow).values(
                    key=fingerprint(f"{key}:{seconds}:{bucket}"),
                    used=amount,
                    expires_at=datetime.fromtimestamp((bucket + 1) * seconds, UTC),
                )
                reserved = statement.on_conflict_do_update(
                    index_elements=[QuotaRow.key],
                    set_={"used": QuotaRow.used + amount},
                    where=QuotaRow.used <= limit - amount,
                ).returning(QuotaRow.used)
                if db.scalar(reserved) is None:
                    raise PlatformError(ErrorCode.RATE_LIMIT, "Request allowance exhausted")

    def reserve_model(self, actor: DevUserContext, tokens: int) -> None:
        if self.settings.mode == "dev":
            return
        self.validate_actor(actor)
        self.reserve(
            [
                ("model:global", 1, self.settings.global_daily_calls),
                ("model:" + actor.user_id, 1, self.settings.user_daily_calls),
                ("tokens:global", tokens, self.settings.global_daily_tokens),
                ("tokens:" + actor.user_id, tokens, self.settings.user_daily_tokens),
            ]
        )

    def actor(self, token: str) -> DevUserContext:
        if len(token) != 43 or not token.isascii():
            raise PlatformError(ErrorCode.AUTH)
        with self.store.factory() as db:
            row = db.get(LoginRow, fingerprint(token))
            account = db.get(AccountRow, row.user_id) if row else None
            if (
                row is None
                or row.expires_at <= datetime.now(UTC)
                or not account
                or not account.enabled
            ):
                raise PlatformError(ErrorCode.AUTH)
            return DevUserContext(
                user_id=account.user_id,
                role=account.role,  # type: ignore[arg-type]
                profile_ids=tuple(account.profile_ids),
            )

    def revalidate(self, request: Request) -> None:
        if self.settings.mode != "dev":
            actor = self.actor(request.cookies.get(self.settings.cookie_name, ""))
            if actor != request.state.actor:
                raise PlatformError(ErrorCode.AUTH)

    def validate_actor(self, actor: DevUserContext) -> None:
        if self.settings.mode == "dev":
            return
        with self.store.factory() as db:
            account = db.get(AccountRow, actor.user_id)
            if (
                account is None
                or not account.enabled
                or account.role != actor.role
                or tuple(account.profile_ids) != actor.profile_ids
            ):
                raise PlatformError(ErrorCode.AUTH)

    def create_account(self, payload: AccountInput) -> dict[str, object]:
        password_hash = PASSWORDS.hash(payload.password.get_secret_value())
        with self.store.factory.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(681432019)"))
            if db.scalar(select(AccountRow).where(AccountRow.username == payload.username.lower())):
                raise PlatformError(ErrorCode.CONFLICT, "Account already exists")
            row = AccountRow(
                user_id=str(uuid4()),
                username=payload.username.lower(),
                password_hash=password_hash,
                role=payload.role,
                profile_ids=payload.profile_ids,
                enabled=True,
                version=1,
            )
            db.add(row)
            db.flush()
            return account_view(row)

    def login(self, payload: LoginInput) -> tuple[str, DevUserContext]:
        username = payload.username.lower()
        self.reserve([("login:global", 1, 100)], seconds=60)
        self.reserve([("login:" + username, 1, 15)], seconds=900)
        with self.store.factory.begin() as db:
            account = db.scalar(
                select(AccountRow).where(AccountRow.username == username).with_for_update()
            )
            try:
                verified: bool = PASSWORDS.verify(
                    account.password_hash if account else DUMMY_HASH,
                    payload.password.get_secret_value(),
                )
            except VerificationError:
                verified = False
            if not verified or account is None or not account.enabled:
                raise PlatformError(ErrorCode.AUTH, "Invalid credentials")
            if PASSWORDS.check_needs_rehash(account.password_hash):
                account.password_hash = PASSWORDS.hash(payload.password.get_secret_value())
            # Keep a bounded set of active devices. Serializing on the account prevents races.
            sessions = list(
                db.scalars(
                    select(LoginRow)
                    .where(LoginRow.user_id == account.user_id)
                    .order_by(LoginRow.expires_at.desc())
                )
            )
            for old in sessions[4:]:
                db.delete(old)
            token = secrets.token_urlsafe(32)
            db.add(
                LoginRow(
                    token_hash=fingerprint(token),
                    user_id=account.user_id,
                    expires_at=datetime.now(UTC) + timedelta(seconds=self.settings.login_ttl),
                )
            )
            actor = DevUserContext(
                user_id=account.user_id,
                role=account.role,  # type: ignore[arg-type]
                profile_ids=tuple(account.profile_ids),
            )
        return token, actor

    def logout(self, token: str) -> None:
        with self.store.factory.begin() as db:
            db.execute(delete(LoginRow).where(LoginRow.token_hash == fingerprint(token)))

    def change_password(self, actor: DevUserContext, payload: PasswordChange) -> None:
        self.reserve([("password:" + actor.user_id, 1, 5)], seconds=900)
        with self.store.factory.begin() as db:
            account = db.get(AccountRow, actor.user_id, with_for_update=True)
            if account is None or not account.enabled:
                raise PlatformError(ErrorCode.AUTH)
            try:
                PASSWORDS.verify(account.password_hash, payload.current_password.get_secret_value())
            except VerificationError:
                raise PlatformError(ErrorCode.PERMISSION, "Password verification failed") from None
            account.password_hash = PASSWORDS.hash(payload.new_password.get_secret_value())
            account.version += 1
            db.execute(delete(LoginRow).where(LoginRow.user_id == actor.user_id))

    def update_account(self, user_id: str, payload: AccountUpdate) -> dict[str, object]:
        with self.store.factory.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(681432019)"))
            account = db.get(AccountRow, user_id, with_for_update=True)
            if account is None:
                raise PlatformError(ErrorCode.NOT_FOUND)
            if account.version != payload.expected_version:
                raise PlatformError(ErrorCode.CONFLICT)
            if (
                account.role == "admin"
                and account.enabled
                and (not payload.enabled or payload.role != "admin")
            ):
                others = db.scalar(
                    select(AccountRow.user_id).where(
                        AccountRow.role == "admin",
                        AccountRow.enabled.is_(True),
                        AccountRow.user_id != user_id,
                    )
                )
                if others is None:
                    raise PlatformError(
                        ErrorCode.PERMISSION, "Cannot remove the last administrator"
                    )
            account.enabled = payload.enabled
            account.role = payload.role
            account.profile_ids = payload.profile_ids
            account.version += 1
            db.execute(delete(LoginRow).where(LoginRow.user_id == user_id))
            return account_view(account)


def csrf_token(token: str) -> str:
    return fingerprint("omniagent-csrf:" + token)


def build_access_router(access: AccessService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["access"])

    def authenticated(request: Request) -> DevUserContext:
        actor: DevUserContext | None = getattr(request.state, "actor", None)
        if actor is None:
            raise PlatformError(ErrorCode.AUTH)
        return actor

    def admin(request: Request) -> DevUserContext:
        actor = authenticated(request)
        if actor.role != "admin":
            raise PlatformError(ErrorCode.PERMISSION)
        return actor

    @router.post("/auth/login")
    def login(payload: LoginInput, request: Request, response: Response) -> dict[str, object]:
        try:
            token, actor = access.login(payload)
        except PlatformError:
            access.audit("login:" + payload.username.lower(), "auth.login_rejected")
            raise
        access.audit(actor.user_id, "auth.login")
        previous = request.cookies.get(access.settings.cookie_name)
        if previous:
            access.logout(previous)
        response.set_cookie(
            access.settings.cookie_name,
            token,
            max_age=access.settings.login_ttl,
            httponly=True,
            secure=access.settings.secure_cookie,
            samesite="strict",
            path="/",
        )
        return {"user": actor.model_dump(), "csrf_token": csrf_token(token)}

    @router.get("/auth/me")
    def me(request: Request) -> dict[str, object]:
        actor = authenticated(request)
        token = request.cookies.get(access.settings.cookie_name, "")
        return {"user": actor.model_dump(), "csrf_token": csrf_token(token)}

    @router.post("/auth/logout", status_code=204)
    def logout(request: Request, response: Response) -> None:
        actor = authenticated(request)
        access.logout(request.cookies.get(access.settings.cookie_name, ""))
        access.audit(actor.user_id, "auth.logout")
        response.delete_cookie(
            access.settings.cookie_name,
            path="/",
            secure=access.settings.secure_cookie,
            httponly=True,
            samesite="strict",
        )

    @router.get("/accounts")
    def accounts(request: Request) -> list[dict[str, object]]:
        admin(request)
        with access.store.factory() as db:
            return [
                account_view(row)
                for row in db.scalars(select(AccountRow).order_by(AccountRow.username).limit(100))
            ]

    @router.post("/auth/password", status_code=204)
    def password(payload: PasswordChange, request: Request, response: Response) -> None:
        actor = authenticated(request)
        access.change_password(actor, payload)
        access.audit(actor.user_id, "auth.password_changed")
        response.delete_cookie(
            access.settings.cookie_name,
            path="/",
            secure=access.settings.secure_cookie,
            httponly=True,
            samesite="strict",
        )

    @router.post("/accounts", status_code=201)
    def create(payload: AccountInput, request: Request) -> dict[str, object]:
        actor = admin(request)
        access.reserve([("accounts:global", 1, 50)])
        result = access.create_account(payload)
        access.audit(actor.user_id, "account.created", str(result["user_id"]))
        return result

    @router.put("/accounts/{user_id}")
    def update(user_id: str, payload: AccountUpdate, request: Request) -> dict[str, object]:
        actor = admin(request)
        result = access.update_account(user_id, payload)
        access.audit(actor.user_id, "account.updated", user_id)
        return result

    return router
