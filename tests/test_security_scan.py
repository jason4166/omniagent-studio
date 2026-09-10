import json
from pathlib import Path

import pytest

from omniagent.security_scan import git, scan

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
