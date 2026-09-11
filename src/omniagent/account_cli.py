"""Local operator account creation/recovery. Passwords arrive on stdin, never in argv."""

import json

from sqlalchemy import delete, select

from omniagent.access import PASSWORDS, AccessService, AccountInput, account_view
from omniagent.access_config import AccessSettings
from omniagent.access_rows import AccountRow, LoginRow
from omniagent.audit import audit_change
from omniagent.database import build_engine
from omniagent.session_store import SessionStore


def manage_account(command: str, url: str, raw: str) -> None:
    store = SessionStore(build_engine(url))
    try:
        if len(raw) > 8192:
            raise ValueError("Oversized account input")
        payload = AccountInput.model_validate_json(raw)
        access = AccessService(store, AccessSettings.from_environment(url))
        with store.factory() as db:
            existing = db.scalar(
                select(AccountRow).where(AccountRow.username == payload.username.lower())
            )
        if command == "account-create":
            if existing is None:
                access.create_account(payload)
            print(json.dumps({"account": payload.username, "created": existing is None}))
        else:
            if existing is None:
                raise ValueError("Account does not exist")
            with store.factory.begin() as db:
                row = db.get(AccountRow, existing.user_id, with_for_update=True)
                if row is None:
                    raise ValueError("Account does not exist")
                before = account_view(row)
                row.password_hash = PASSWORDS.hash(payload.password.get_secret_value())
                row.version += 1
                db.execute(delete(LoginRow).where(LoginRow.user_id == row.user_id))
                audit_change(
                    db,
                    "local-operator",
                    "account.password_rotated",
                    row.user_id,
                    before=before,
                    after=account_view(row),
                )
            print(json.dumps({"account": payload.username, "password_rotated": True}))
    except Exception:
        raise SystemExit(
            "Account operation failed; check input and database configuration"
        ) from None
    finally:
        store.engine.dispose()
