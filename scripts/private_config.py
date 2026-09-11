"""Initialize per-installation credentials once; never emit their values or overwrite them."""

import json
import os
import secrets
from pathlib import Path


def private_directory(
    root: Path,
    project: str,
    *,
    create: bool = False,
    test_accounts: bool = False,
    real_provider: bool = False,
) -> Path:
    parent = root.resolve() / ".local" / "deployments"
    directory = parent / project
    if directory.resolve() != directory or parent.resolve() != parent:
        raise ValueError("Private configuration cannot follow symlinks")
    if not create:
        return directory
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)

    def write_once(name: str, value: str) -> str:
        path = directory / name
        if path.exists():
            if path.is_symlink():
                raise ValueError("Private files cannot be symlinks")
            return path.read_text(encoding="utf-8")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
        return value

    owner = write_once("database_password", secrets.token_urlsafe(36))
    runtime = write_once("runtime_password", secrets.token_urlsafe(36))
    mock = write_once("mock_password", secrets.token_urlsafe(36))
    for name, user, password in [
        ("owner_url", "omniagent", owner),
        ("database_url", "omniagent_runtime", runtime),
        ("mock_url", "omniagent_mock", mock),
    ]:
        write_once(name, f"postgresql+psycopg://{user}:{password}@postgres:5432/omniagent")
    if real_provider:
        for name, variable in [
            ("chat_key", "DEEPSEEK_API_KEY"),
            ("embedding_key", "ZHIPUAI_API_KEY"),
        ]:
            if not (directory / name).exists():
                value = os.environ.get(variable, "")
                if not 8 <= len(value) <= 8192:
                    raise ValueError(f"Configure {variable} before initializing real mode")
                write_once(name, value)
    # Compose bind secrets retain host file permissions. The 0700 parent protects host access;
    # each selected container receives a read-only file readable by its own non-root UID.
    for name in (
        "database_password",
        "database_url",
        "owner_url",
        "runtime_password",
        "mock_password",
        "mock_url",
        "chat_key",
        "embedding_key",
    ):
        if (directory / name).exists():
            os.chmod(directory / name, 0o444)
    write_once(
        "admin.json",
        json.dumps(
            {
                "username": "admin",
                "password": secrets.token_urlsafe(24),
                "role": "admin",
                "profile_ids": ["hr", "support", "sales"],
            }
        ),
    )
    if test_accounts:
        for role in ("member", "viewer"):
            write_once(
                f"{role}.json",
                json.dumps(
                    {
                        "username": "test-" + role,
                        "password": secrets.token_urlsafe(24),
                        "role": role,
                        "profile_ids": ["hr", "support", "sales"],
                    }
                ),
            )
    return directory
