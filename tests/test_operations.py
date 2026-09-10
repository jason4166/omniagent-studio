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
