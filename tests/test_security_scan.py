import json
from pathlib import Path

import pytest

from omniagent.security_scan import findings, git, revision, scan

pytestmark = pytest.mark.security


def test_compose_secret_directory_reference_is_not_a_secret_but_values_still_are(monkeypatch):
    directory = "/home/runner/work/example/.local/deployments/omniagent-ci-review"
    value = "fixture-password-" + "q" * 20
    monkeypatch.setenv("OMNIAGENT_SECRET_DIR", directory)
    monkeypatch.setenv("OMNIAGENT_RUNTIME_PASSWORD", value)
    raw = json.dumps({"secrets": {"password": {"file": directory + "/password"}}}).encode()
    assert findings(raw, "compose-config", "test") == []
    hits = findings(raw + value.encode(), "compose-config", "test")
    assert len(hits) == 1 and hits[0]["rule"] == "configured_secret"
    assert value not in json.dumps(hits)


def test_file_backed_secret_literals_are_scanned_without_requiring_environment_values():
    value = "file-backed-fixture-" + "x" * 24
    hits = findings(value.encode(), "image-config", "test", literal_secrets=(value,))
    assert len(hits) == 1 and hits[0]["rule"] == "configured_secret"
    assert value not in json.dumps(hits)


def test_removed_secret_is_detected_in_reachable_history_without_printing_it(tmp_path: Path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Synthetic scanner fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    synthetic = "sk-" + "z" * 32
    source = tmp_path / "example.txt"
    source.write_text(synthetic, encoding="utf-8")
    git(tmp_path, "add", "--", "example.txt")
    git(tmp_path, "commit", "-qm", "synthetic test fixture")
    source.write_text("removed from working copy", encoding="utf-8")
    git(tmp_path, "add", "--", "example.txt")
    git(tmp_path, "commit", "-qm", "remove synthetic fixture")
    report = scan(tmp_path, tmp_path / "report")
    assert report["status"] == "fail" and report["finding_count"] == 1
    assert synthetic not in json.dumps(report)
    assert report["findings"][0]["revision"] != "worktree"


@pytest.mark.parametrize("value", ["", "development", "../untrusted", "f" * 39])
def test_container_reports_require_full_build_revision(tmp_path, monkeypatch, value):
    monkeypatch.setenv("OMNIAGENT_GIT_REVISION", value)
    with pytest.raises(ValueError, match="build Git revision"):
        revision(tmp_path)


def test_checkout_revision_wins_over_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIAGENT_GIT_REVISION", "a" * 40)
    assert revision(tmp_path) == "a" * 40
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Synthetic revision fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    git(tmp_path, "commit", "--allow-empty", "-qm", "revision fixture")
    assert revision(tmp_path) == git(tmp_path, "rev-parse", "HEAD").decode().strip()
