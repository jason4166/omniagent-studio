"""Encrypted PostgreSQL snapshots; restore always creates a new database, never overwrites."""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from ops import ROOT, compose_arguments
from private_config import private_directory

HEADER = b"OMNIAGENT-BACKUP-V1\n"
MAX_BYTES = 128 * 1024 * 1024


def command(arguments: list[str], *, source=None, destination=None) -> bytes:
    executable = shutil.which(arguments[0])
    if executable is None:
        raise RuntimeError("Docker is required")
    result = subprocess.run(  # noqa: S603 - fixed container utilities; no shell
        [executable, *arguments[1:]],
        cwd=ROOT,
        stdin=source,
        stdout=destination or subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Database backup operation failed; original database is unchanged")
    return result.stdout or b""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["backup", "restore"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    compose = compose_arguments(args.project)
    private = private_directory(ROOT, args.project)
    os.environ["OMNIAGENT_SECRET_DIR"] = str(private)
    key_path = private / "backup.key"
    if not private.is_dir():
        parser.error("Deployment private directory is missing")
    if not key_path.exists() and args.command == "backup":
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(AESGCM.generate_key(bit_length=256))
    if key_path.is_symlink() or not key_path.is_file() or key_path.stat().st_size != 32:
        parser.error("The original private backup key is required")
    if os.name == "posix" and key_path.stat().st_mode & 0o077:
        parser.error("Backup key must be owner-readable only")
    cipher = AESGCM(key_path.read_bytes())
    output = private / "backups"
    output.mkdir(mode=0o700, exist_ok=True)
    base = [*compose, "exec", "-T", "postgres"]
    with tempfile.TemporaryFile(dir=private) as temporary:
        if args.command == "backup":
            command(
                [*base, "pg_dump", "-U", "omniagent", "-d", "omniagent", "-Fc", "-Z", "9"],
                destination=temporary,
            )
            if temporary.tell() > MAX_BYTES:
                parser.error(
                    "Snapshot exceeds the bounded backup size; use a streaming operator backup"
                )
            temporary.seek(0)
            plaintext = temporary.read(MAX_BYTES + 1)
            nonce = secrets.token_bytes(12)
            encrypted = HEADER + nonce + cipher.encrypt(nonce, plaintext, HEADER)
            path = output / (
                datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8] + ".oab"
            )
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encrypted)
            print(
                json.dumps(
                    {
                        "encrypted_backup": str(path),
                        "bytes": len(encrypted),
                        "original_database_unchanged": True,
                    }
                )
            )
        else:
            if args.input is None or args.input.stat().st_size > MAX_BYTES + 128:
                parser.error("An encrypted bounded backup file is required")
            raw = args.input.read_bytes()
            if not raw.startswith(HEADER):
                parser.error("Unsupported backup format")
            nonce = raw[len(HEADER) : len(HEADER) + 12]
            # Authenticate the complete snapshot before creating a database or writing SQL.
            plaintext = cipher.decrypt(nonce, raw[len(HEADER) + 12 :], HEADER)
            if not plaintext.startswith(b"PGDMP"):
                parser.error("Invalid archive")
            temporary.write(plaintext)
            temporary.seek(0)
            target = "omniagent_restore_" + uuid4().hex[:12]
            command([*base, "createdb", "-U", "omniagent", target])
            command(
                [
                    *base,
                    "pg_restore",
                    "--exit-on-error",
                    "--single-transaction",
                    "-U",
                    "omniagent",
                    "-d",
                    target,
                ],
                source=temporary,
            )
            statement = (
                "DELETE FROM login_sessions; SELECT json_build_object("
                "'sessions',(SELECT count(*) FROM sessions),"
                "'approvals',(SELECT count(*) FROM approvals),"
                "'effects',(SELECT count(*) FROM mock_effects),"
                "'checkpoints',(SELECT count(*) FROM checkpoints));"
            )
            counts = (
                command([*base, "psql", "-U", "omniagent", "-d", target, "-At", "-c", statement])
                .decode()
                .splitlines()[-1]
            )
            print(
                json.dumps(
                    {
                        "restored_database": target,
                        "counts": json.loads(counts),
                        "login_sessions_revoked": True,
                        "original_database_unchanged": True,
                    }
                )
            )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Backup/restore failed; no original database was overwritten") from None
