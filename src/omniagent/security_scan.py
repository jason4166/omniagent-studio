"""Scan publishable worktree files and every Git-reachable blob without printing secrets."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from omniagent.redaction import secret_values

RULES = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{24,}\b"),
    "aws_access_key": re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
}


def revision(root: Path) -> str:
    if (root / ".git").exists():
        return git(root, "rev-parse", "HEAD").decode().strip()
    configured = os.environ.get("OMNIAGENT_GIT_REVISION", "")
    if not re.fullmatch(r"[0-9a-f]{40}", configured):
        raise ValueError("Container evaluation requires a 40-character build Git revision")
    return configured


def git(root: Path, *arguments: str, data: bytes | None = None) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git is required for the reachable-history scan")
    return subprocess.run(  # noqa: S603 - fixed Git commands, no shell
        [executable, *arguments], cwd=root, input=data, capture_output=True, check=True, timeout=60
    ).stdout


def findings(raw: bytes, path: str, revision: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for name, pattern in RULES.items():
        for match in pattern.finditer(raw):
            result.append(
                {
                    "rule": name,
                    "path": path,
                    "revision": revision,
                    "line": raw[: match.start()].count(b"\n") + 1,
                    "fingerprint": hashlib.sha256(match.group()).hexdigest(),
                }
            )
    for secret in secret_values():
        if secret.encode() in raw:
            result.append(
                {
                    "rule": "configured_secret",
                    "path": path,
                    "revision": revision,
                    "fingerprint": hashlib.sha256(secret.encode()).hexdigest(),
                }
            )
    return result


def scan(root: Path, output_dir: Path) -> dict[str, object]:
    root = root.resolve()
    files = set(git(root, "ls-files", "-z").split(b"\0")) | set(
        git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    )
    hits: list[dict[str, object]] = []
    count = 0
    for encoded in sorted(files):
        if not encoded:
            continue
        path = encoded.decode("utf-8")
        target = (root / path).resolve()
        if not target.is_relative_to(root) or target.is_symlink():
            raise ValueError("Worktree scan cannot follow external files")
        if not target.is_file():
            continue
        count += 1
        hits.extend(findings(target.read_bytes(), path, "worktree"))
        if target.name == ".env" or target.suffix in {".pem", ".p12", ".pfx"}:
            hits.append({"rule": "credential_file", "path": path, "revision": "worktree"})
    objects: dict[str, str] = {}
    for line in git(root, "rev-list", "--objects", "--all").decode().splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            objects[parts[0]] = parts[1]
    raw = git(root, "cat-file", "--batch", data=("\n".join(objects) + "\n").encode())
    offset = 0
    blobs = 0
    while offset < len(raw):
        end = raw.index(b"\n", offset)
        identifier, kind, size_raw = raw[offset:end].split()
        size = int(size_raw)
        payload = raw[end + 1 : end + 1 + size]
        if kind == b"blob":
            blobs += 1
            revision = identifier.decode()
            path = objects[revision]
            hits.extend(findings(payload, path, revision))
            if Path(path).name == ".env" or Path(path).suffix in {".pem", ".p12", ".pfx"}:
                hits.append({"rule": "credential_file", "path": path, "revision": revision})
        offset = end + 2 + size
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "pass" if not hits else "fail",
        "working_files": count,
        "reachable_blobs": blobs,
        "finding_count": len(hits),
        "findings": hits,
        "scope": (
            "Git tracked and unignored candidate files; every blob reachable from all local refs. "
            "Ignored local environments, dependencies and private runtime data are excluded "
            "from publication scanning."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "secret-scan.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / "secret-scan.md").write_text(
        f"# Secret and reachable-history scan\n\nStatus: **{report['status']}**.\n\n"
        f"Worktree files: {count}; reachable blobs: {blobs}; findings: {len(hits)}.\n\n"
        f"{report['scope']}\n\nFindings contain rule names, locations and fingerprints only. "
        "A passing pattern scan does not establish the absence of every possible secret.\n",
        encoding="utf-8",
    )
    return report
