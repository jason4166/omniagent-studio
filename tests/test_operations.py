"""Destructive maintenance must reject an unconfirmed or foreign target before mutation."""

import importlib.util
import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest


@pytest.fixture
def operations(monkeypatch, tmp_path):
    for name in ("OMNIAGENT_GIT_REVISION", "OMNIAGENT_TEST_UID", "OMNIAGENT_TEST_GID"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    location = Path(__file__).resolve().parents[1] / "scripts" / "ops.py"
    monkeypatch.syspath_prepend(str(location.parent))
    spec = importlib.util.spec_from_file_location("release_operations", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.mark.parametrize("project", ["../user-data", "other-project", "omniagent;echo", ""])
def test_operations_reject_invalid_targets_before_any_command(operations, monkeypatch, project):
    def forbidden(*args, **kwargs):
        pytest.fail("An invalid target must not execute any command")

    monkeypatch.setattr(operations, "run", forbidden)
    monkeypatch.setattr(sys, "argv", ["ops.py", "reset", "--project", project])
    with pytest.raises(SystemExit):
        operations.main()


@pytest.mark.parametrize("confirmed,foreign", [(False, False), (True, True)])
def test_reset_requires_confirmation_and_matching_volume_ownership(
    operations, monkeypatch, confirmed, foreign
):
    calls = []

    def command(arguments, **kwargs):
        calls.append(arguments)
        if arguments[0] == "git":
            return "a" * 40
        if arguments[1:3] == ["volume", "ls"]:
            return "omniagent-test-owned_pgdata"
        if arguments[1:3] == ["volume", "inspect"]:
            return json.dumps(
                [
                    {
                        "Labels": {
                            "com.docker.compose.project": "foreign"
                            if foreign
                            else "omniagent-test-owned"
                        }
                    }
                ]
            )
        pytest.fail("Unsafe reset reached a mutating command")

    monkeypatch.setattr(operations, "run", command)
    args = ["ops.py", "reset", "--project", "omniagent-test-owned"]
    if confirmed:
        args.extend(["--confirm-reset", "omniagent-test-owned"])
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit):
        operations.main()
    assert not any("down" in call or "rm" in call for call in calls)


def test_production_project_cannot_downgrade_to_offline_evaluation(
    operations, monkeypatch, tmp_path
):
    private = tmp_path / ".local" / "deployments" / "omniagent-test-pinned"
    private.mkdir(parents=True)
    (private / "deployment.json").write_text(
        json.dumps(
            {"environment": "production", "mode": "fake", "origin": "https://studio.example"}
        )
    )
    monkeypatch.setattr(
        operations, "run", lambda *args, **kwargs: pytest.fail("Must reject before running Docker")
    )
    monkeypatch.setattr(sys, "argv", ["ops.py", "eval", "--project", "omniagent-test-pinned"])
    with pytest.raises(SystemExit):
        operations.main()


def test_private_configuration_is_unique_repeatable_and_separate(operations, tmp_path):
    from private_config import private_directory

    first = private_directory(tmp_path, "omniagent-test-one", create=True)
    snapshot = {path.name: path.read_bytes() for path in first.iterdir()}
    private_directory(tmp_path, "omniagent-test-one", create=True)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == snapshot
    second = private_directory(tmp_path, "omniagent-test-two", create=True)
    assert (second / "database_password").read_bytes() != snapshot["database_password"]
    assert len(snapshot["database_password"]) >= 32
    assert not (first / "member.json").exists()
    if os.name == "posix":
        assert first.stat().st_mode & 0o777 == 0o700
        assert (first / "database_password").stat().st_mode & 0o777 == 0o444
        assert (first / "admin.json").stat().st_mode & 0o777 == 0o600


def test_tampered_backup_never_reaches_a_database_command(operations, monkeypatch, tmp_path):
    import backup
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from private_config import private_directory

    private = private_directory(tmp_path, "omniagent-test-restore", create=True)
    key = AESGCM.generate_key(bit_length=256)
    key_file = private / "backup.key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    nonce = b"n" * 12
    raw = bytearray(
        backup.HEADER + nonce + AESGCM(key).encrypt(nonce, b"PGDMPsynthetic", backup.HEADER)
    )
    raw[-1] ^= 1
    archive = tmp_path / "tampered.oab"
    archive.write_bytes(raw)
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    monkeypatch.setattr(
        backup,
        "command",
        lambda *a, **kw: pytest.fail("No database mutation before authentication"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["backup.py", "restore", "--project", "omniagent-test-restore", "--input", str(archive)],
    )
    with pytest.raises(InvalidTag):
        backup.main()


@pytest.mark.parametrize("unavailable", [False, True])
def test_acceptance_always_preserves_evidence_when_cleanup_is_unavailable(
    monkeypatch, tmp_path, unavailable
):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    import acceptance

    class Endpoint:
        def request(self, method, path):
            if unavailable:
                raise urllib.error.URLError("synthetic unavailable API")

    report = {"passed": True}
    if unavailable:
        with pytest.raises(RuntimeError, match="report was preserved"):
            acceptance.finish_report(Endpoint(), ["owned"], tmp_path, report, keep_sessions=False)
    else:
        acceptance.finish_report(Endpoint(), ["owned"], tmp_path, report, keep_sessions=False)
    saved = json.loads((tmp_path / "acceptance.json").read_text(encoding="utf-8"))
    assert saved["passed"] is not unavailable
    assert saved["sessions_retained"] == (["owned"] if unavailable else [])
