"""Local development identities. Caller-supplied roles are never authoritative."""

import hmac
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict

from omniagent.errors import ErrorCode, PlatformError
from omniagent.profiles import AgentProfile


class DevUserContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: str
    role: Literal["admin", "member", "viewer"]
    profile_ids: tuple[str, ...] = ()

    def authorize_profile(self, profile: AgentProfile) -> None:
        if (
            not profile.enabled
            or self.role not in profile.allowed_roles
            or (self.role != "admin" and profile.profile_id not in self.profile_ids)
        ):
            raise PlatformError(ErrorCode.PERMISSION)


def authenticate(authorization: str | None) -> DevUserContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise PlatformError(ErrorCode.AUTH)
    value = authorization.removeprefix("Bearer ")
    roles: tuple[Literal["admin", "member", "viewer"], ...] = ("admin", "member", "viewer")
    for role in roles:
        expected = os.environ.get(f"OMNIAGENT_DEV_{role.upper()}_TOKEN", f"local-demo-{role}")
        if hmac.compare_digest(value, expected):
            return DevUserContext(
                user_id=f"demo-{role}", role=role, profile_ids=("hr", "support", "sales")
            )
    raise PlatformError(ErrorCode.AUTH)
