"""Fail-closed deployment settings; developer credentials require explicit test mode."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url


def bounded_setting(name: str, default: int, maximum: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if not 1 <= value <= maximum:
        raise ValueError(f"Invalid bounded setting: {name}")
    return value


@dataclass(frozen=True)
class AccessSettings:
    mode: str
    origin: str
    production: bool
    secure_cookie: bool
    login_ttl: int
    user_daily_calls: int
    global_daily_calls: int
    user_daily_tokens: int
    global_daily_tokens: int

    @classmethod
    def from_environment(cls, database_url: str) -> "AccessSettings":
        environment = os.environ.get("OMNIAGENT_ENV", "local")
        mode = os.environ.get("OMNIAGENT_AUTH_MODE", "password")
        if environment not in {"local", "production", "test"} or mode not in {"password", "dev"}:
            raise ValueError("Unknown deployment/authentication mode")
        if mode == "dev" and environment != "test":
            raise ValueError("Developer credentials are restricted to explicit test mode")
        origin = os.environ.get("OMNIAGENT_PUBLIC_ORIGIN", "http://127.0.0.1:8080")
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("PUBLIC_ORIGIN must be an exact HTTP(S) origin without a path")
        production = environment == "production"
        if production and parsed.scheme != "https":
            raise ValueError("Production requires HTTPS")
        if not production and parsed.hostname not in {"127.0.0.1", "localhost", "[::1]", "::1"}:
            if environment != "test":
                raise ValueError("Public hosts require production mode")
        if production:
            database = make_url(database_url)
            if not database.password or len(database.password) < 24:
                raise ValueError("Production requires a dedicated database credential")
            if any(key.startswith("OMNIAGENT_DEV_") for key in os.environ):
                raise ValueError("Developer credentials are forbidden in production")
        return cls(
            mode=mode,
            origin=origin,
            production=production,
            secure_cookie=parsed.scheme == "https",
            login_ttl=bounded_setting("OMNIAGENT_LOGIN_TTL_SECONDS", 28800, 86400),
            user_daily_calls=bounded_setting("OMNIAGENT_USER_DAILY_MODEL_CALLS", 100, 10000),
            global_daily_calls=bounded_setting("OMNIAGENT_GLOBAL_DAILY_MODEL_CALLS", 1000, 100000),
            user_daily_tokens=bounded_setting("OMNIAGENT_USER_DAILY_TOKENS", 500000, 10000000),
            global_daily_tokens=bounded_setting(
                "OMNIAGENT_GLOBAL_DAILY_TOKENS", 2000000, 100000000
            ),
        )

    @property
    def cookie_name(self) -> str:
        return "__Host-omniagent_session" if self.secure_cookie else "omniagent_local_session"
