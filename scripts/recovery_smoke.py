"""Exercise encrypted backup of a pending approval in an isolated local deployment."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from acceptance import API
from ops import ROOT, compose_arguments, run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compose = compose_arguments(args.project)
    if not args.project.startswith(("omniagent-test-", "omniagent-clean-")):
        parser.error("Recovery smoke requires a disposable test or clean project")
    private = ROOT / ".local" / "deployments" / args.project
    metadata = json.loads((private / "deployment.json").read_text(encoding="utf-8"))
    if metadata["environment"] != "local" or metadata["mode"] != "fake":
        parser.error("Recovery smoke requires a local Fake deployment")
    os.environ["OMNIAGENT_SECRET_DIR"] = str(private)
    args.output.mkdir(parents=True, exist_ok=True)
    api = API(args.base_url, private)
    thread = api.request("POST", "/api/sessions", {"profile_id": "sales"})["thread_id"]
    report: dict[str, object] = {"passed": False}

    def sql(database: str, statement: str) -> str:
        return run(
            [
                *compose,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "omniagent",
                "-d",
                database,
                "-At",
                "-c",
                statement,
            ],
            capture=True,
        )

    try:
        proposed = api.request(
            "POST",
            f"/api/sessions/{thread}/messages",
            {"message": "为客户 C-100 创建回访，备注：恢复演练", "request_key": uuid4().hex},
        )
        if proposed["status"] != "awaiting_approval":
            raise RuntimeError("A persisted pending approval is required")
        command = [sys.executable, str(ROOT / "scripts/backup.py")]
        backup = json.loads(run([*command, "backup", "--project", args.project], capture=True))
        restored = json.loads(
            run(
                [
                    *command,
                    "restore",
                    "--project",
                    args.project,
                    "--input",
                    backup["encrypted_backup"],
                ],
                capture=True,
            )
        )
        target = restored["restored_database"]
        if not (
            restored["counts"]["sessions"]
            and restored["counts"]["approvals"]
            and restored["counts"]["checkpoints"]
        ):
            raise RuntimeError("Snapshot did not retain the resumable workflow")
        snapshot = "SELECT count(*) FROM approvals WHERE status='pending'"
        if (
            int(sql(target, snapshot)) < 1
            or sql(target, "SELECT count(*) FROM login_sessions") != "0"
        ):
            raise RuntimeError("Pending approval or login revocation failed")
        before = sql("postgres", "SELECT datname FROM pg_database ORDER BY datname")
        damaged = bytearray(Path(backup["encrypted_backup"]).read_bytes())
        damaged[-1] ^= 1
        tampered = args.output / "tampered.oab"
        tampered.write_bytes(damaged)
        result = subprocess.run(  # noqa: S603 - fixed local script and owned encrypted archive
            [*command, "restore", "--project", args.project, "--input", str(tampered)],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0 or before != sql(
            "postgres", "SELECT datname FROM pg_database ORDER BY datname"
        ):
            raise RuntimeError("Tampered archive was not rejected before database mutation")
        unchanged = api.request("GET", f"/api/sessions/{thread}")
        if unchanged["status"] != "awaiting_approval":
            raise RuntimeError("Original workflow changed during the restore")
        report.update(
            {
                "passed": True,
                "source_commit": run(["git", "rev-parse", "HEAD"], capture=True),
                "encrypted_archive_bytes": backup["bytes"],
                "restored_counts": restored["counts"],
                "pending_approval_preserved": True,
                "login_sessions_revoked": True,
                "tampering_rejected_before_database_creation": True,
                "original_database_unchanged": True,
                "scope": "New restore database; deployment promotion requires an operator",
            }
        )
    finally:
        try:
            api.request("DELETE", f"/api/sessions/{thread}")
        except Exception:
            report["passed"] = False
            report["cleanup_failed"] = True
        (args.output / "recovery.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    if not report["passed"]:
        raise SystemExit("Recovery gate failed; evidence was preserved")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
