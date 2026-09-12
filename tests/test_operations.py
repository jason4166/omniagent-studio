"""Destructive maintenance must reject an unconfirmed or foreign target before mutation."""

import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest


@pytest.fixture
def operations(monkeypatch, tmp_path):
    for name in (
        "OMNIAGENT_GIT_REVISION",
        "OMNIAGENT_TEST_UID",
        "OMNIAGENT_TEST_GID",
        "OMNIAGENT_WEB_PORT",
        "OMNIAGENT_PUBLIC_ORIGIN",
        "OMNIAGENT_SECRET_DIR",
        "OMNIAGENT_PUBLIC_PREVIEW_ENABLED",
        "OMNIAGENT_PUBLIC_PREVIEW_PROFILE_IDS",
    ):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    location = Path(__file__).resolve().parents[1] / "scripts" / "ops.py"
    monkeypatch.syspath_prepend(str(location.parent))
    spec = importlib.util.spec_from_file_location("release_operations", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.mark.parametrize("command", ["bootstrap", "up"])
@pytest.mark.parametrize("environment", ["local", "production"])
def test_preloaded_start_never_builds_or_pulls_and_preserves_startup_checks(
    operations, monkeypatch, command, environment
):
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return "a" * 40 if arguments[0] == "git" else ""

    monkeypatch.setattr(operations, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ops.py",
            command,
            "--project",
            "omniagent-test-preloaded",
            "--environment",
            environment,
            "--origin",
            "https://studio.example" if environment == "production" else "http://127.0.0.1:18123",
            "--skip-build",
        ],
    )
    operations.main()
    compose = operations.compose_arguments("omniagent-test-preloaded")
    if environment == "production":
        compose += ["-f", str(operations.ROOT / "compose.production.yaml")]
    assert calls == [
        ["git", "rev-parse", "HEAD"],
        [*compose, "config", "--quiet"],
        [*compose, "up", "-d", "--wait", "--wait-timeout", "120", "--no-build", "--pull", "never"],
        [*compose, "exec", "-T", "api", "omniagent", "account-create"],
    ]


@pytest.mark.parametrize("environment", ["local", "production"])
def test_default_start_still_builds_before_up(operations, monkeypatch, environment):
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return "a" * 40 if arguments[0] == "git" else ""

    monkeypatch.setattr(operations, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ops.py",
            "up",
            "--environment",
            environment,
            "--origin",
            "https://studio.example" if environment == "production" else "http://127.0.0.1:18123",
        ],
    )
    operations.main()
    build = next(call for call in calls if "build" in call)
    up = next(call for call in calls if "up" in call)
    assert build[build.index("build") :] == [
        "build",
        "migrate",
        "mock",
        "web",
        *(["edge"] if environment == "production" else []),
    ]
    assert calls.index(build) < calls.index(up)
    assert up[up.index("up") :] == ["up", "-d", "--wait", "--wait-timeout", "120"]


def test_missing_preloaded_image_stops_without_build_pull_or_account_bootstrap(
    operations, monkeypatch
):
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        if "up" in arguments:
            assert arguments[-3:] == ["--no-build", "--pull", "never"]
            raise subprocess.CalledProcessError(1, arguments, stderr="Image not found locally")
        if "build" in arguments or "exec" in arguments:
            pytest.fail("Missing images must not trigger a build or account creation")
        return "a" * 40 if arguments[0] == "git" else ""

    monkeypatch.setattr(operations, "run", run)
    monkeypatch.setattr(sys, "argv", ["ops.py", "up", "--skip-build"])
    with pytest.raises(subprocess.CalledProcessError):
        operations.main()
    assert len(calls) == 3


@pytest.mark.parametrize("command", ["test", "eval", "eval-real", "health", "seed"])
def test_skip_build_rejects_commands_outside_startup_before_any_side_effect(
    operations, monkeypatch, tmp_path, command
):
    monkeypatch.setattr(
        operations, "run", lambda *a, **kw: pytest.fail("Invalid command reached Docker")
    )
    monkeypatch.setattr(sys, "argv", ["ops.py", command, "--skip-build"])
    with pytest.raises(SystemExit):
        operations.main()
    assert not (tmp_path / ".local").exists()


def test_public_preview_is_opt_in_persisted_and_explicitly_revocable(
    operations, monkeypatch, tmp_path
):
    monkeypatch.setenv("OMNIAGENT_PUBLIC_ORIGIN", "")
    monkeypatch.setattr(operations, "run", lambda *a, **kw: "a" * 40)
    base = ["ops.py", "up", "--project", "omniagent-test-preview"]
    metadata = tmp_path / ".local/deployments/omniagent-test-preview/deployment.json"
    monkeypatch.setattr(sys, "argv", base)
    operations.main()
    assert json.loads(metadata.read_text())["public_preview"] is False
    monkeypatch.setattr(
        sys, "argv", [*base, "--public-preview", "--preview-profiles", "hr,support"]
    )
    operations.main()
    assert json.loads(metadata.read_text())["preview_profiles"] == ["hr", "support"]
    monkeypatch.setenv("OMNIAGENT_PUBLIC_PREVIEW_ENABLED", "false")
    monkeypatch.setattr(sys, "argv", base)
    operations.main()
    assert os.environ["OMNIAGENT_PUBLIC_PREVIEW_ENABLED"] == "true"
    assert os.environ["OMNIAGENT_PUBLIC_PREVIEW_PROFILE_IDS"] == "hr,support"
    monkeypatch.setattr(sys, "argv", [*base, "--no-public-preview"])
    operations.main()
    assert json.loads(metadata.read_text())["public_preview"] is False


@pytest.mark.parametrize("profiles", ["", "hr,", "hr,hr", "hr,../private", "hr, support"])
def test_public_preview_scope_rejects_invalid_input_before_commands(
    operations, monkeypatch, profiles
):
    monkeypatch.setattr(
        operations, "run", lambda *a, **kw: pytest.fail("Invalid scope reached Docker")
    )
    monkeypatch.setattr(sys, "argv", ["ops.py", "up", "--preview-profiles", profiles])
    with pytest.raises(SystemExit):
        operations.main()


@pytest.mark.parametrize("inherited_port", [None, "8080", ""])
def test_restarting_saved_local_project_restores_its_port(
    operations, monkeypatch, tmp_path, inherited_port
):
    private = tmp_path / ".local/deployments/omniagent-test-port"
    private.mkdir(parents=True)
    (private / "deployment.json").write_text(
        json.dumps({"environment": "local", "mode": "fake", "origin": "http://127.0.0.1:18123"})
    )
    (private / "admin.json").write_text("{}")
    if inherited_port is None:
        monkeypatch.delenv("OMNIAGENT_WEB_PORT", raising=False)
    else:
        monkeypatch.setenv("OMNIAGENT_WEB_PORT", inherited_port)
    monkeypatch.setattr(operations, "private_directory", lambda *a, **kw: private)
    observed = []

    def command(arguments, **kwargs):
        if arguments[0] == "docker":
            observed.append(os.environ["OMNIAGENT_WEB_PORT"])
        return "a" * 40 if arguments[0] == "git" else ""

    monkeypatch.setattr(operations, "run", command)
    monkeypatch.setattr(sys, "argv", ["ops.py", "up", "--project", "omniagent-test-port"])
    operations.main()
    assert observed and set(observed) == {"18123"}
    assert os.environ["OMNIAGENT_PUBLIC_ORIGIN"] == "http://127.0.0.1:18123"


def test_explicit_port_creates_matching_origin_and_cannot_retarget_saved_project(
    operations, monkeypatch, tmp_path
):
    monkeypatch.setenv("OMNIAGENT_PUBLIC_ORIGIN", "")
    monkeypatch.setattr(operations, "run", lambda *a, **kw: "a" * 40)
    base = ["ops.py", "up", "--project", "omniagent-test-port", "--port"]
    monkeypatch.setattr(sys, "argv", [*base, "18123"])
    operations.main()
    saved = json.loads(
        (tmp_path / ".local/deployments/omniagent-test-port/deployment.json").read_text()
    )
    assert saved["origin"] == "http://127.0.0.1:18123"
    monkeypatch.setattr(
        operations, "run", lambda *a, **kw: pytest.fail("Port mismatch must reject before Docker")
    )
    monkeypatch.setattr(sys, "argv", [*base, "18124"])
    with pytest.raises(SystemExit):
        operations.main()


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
