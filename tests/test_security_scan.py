import json
from pathlib import Path

import pytest

from omniagent.security_scan import git, revision, scan

pytestmark = pytest.mark.security


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
