"""Portable, explicitly scoped Docker operations. Requires only Python, Git and Docker."""

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str], *, capture: bool = False, timeout: int = 1200) -> str:
    executable = shutil.which(arguments[0])
    if executable is None:
        raise SystemExit(f"Required executable unavailable: {arguments[0]}")
    result = subprocess.run(  # noqa: S603 - fixed commands and validated project; no shell
        [executable, *arguments[1:]],
        cwd=ROOT,
        check=True,
        timeout=timeout,
        text=True,
        encoding="utf-8",
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "bootstrap",
            "up",
            "down",
            "reset",
            "health",
            "test",
            "eval",
            "benchmark",
            "seed",
            "purge",
        ],
    )
    parser.add_argument("--project", default="omniagent-v1")
    parser.add_argument("--confirm-reset")
    args = parser.parse_args()
    if not re.fullmatch(r"omniagent-(v1|clean|ci|test)[a-z0-9-]*", args.project):
        parser.error("Use an explicitly scoped omniagent-v1/clean/ci/test project name")
    compose = ["docker", "compose", "-p", args.project, "-f", str(ROOT / "compose.yaml")]
    os.environ["OMNIAGENT_GIT_REVISION"] = run(["git", "rev-parse", "HEAD"], capture=True)
    if hasattr(os, "getuid"):
        os.environ["OMNIAGENT_TEST_UID"] = str(os.getuid())
        os.environ["OMNIAGENT_TEST_GID"] = str(os.getgid())
    (ROOT / ".pytest-tmp-container-reports").mkdir(exist_ok=True)
    if args.command in {"bootstrap", "up"}:
        run([*compose, "config", "--quiet"])
        run([*compose, "build", "migrate", "mock", "web"])
        run([*compose, "up", "-d", "--wait", "--wait-timeout", "120"])
    elif args.command == "down":
        run([*compose, "down"])
    elif args.command == "reset":
        volumes = run(
            [
                "docker",
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={args.project}",
                "--format",
                "{{.Name}}",
            ],
            capture=True,
        ).splitlines()
        if args.confirm_reset != args.project:
            parser.error(
                f"WARNING: reset permanently deletes {args.project} volumes {volumes}. "
                f"Repeat with --confirm-reset {args.project} only to erase this project."
            )
        for volume in volumes:
            details = json.loads(run(["docker", "volume", "inspect", volume], capture=True))[0]
            if (
                not volume.startswith(args.project + "_")
                or details["Labels"].get("com.docker.compose.project") != args.project
            ):
                raise SystemExit("Refusing to delete a volume outside the selected project")
        print(f"WARNING: permanently deleting project volumes: {volumes}", flush=True)
        run([*compose, "down"])
        if volumes:
            run(["docker", "volume", "rm", *volumes])
    elif args.command == "health":
        run([*compose, "ps", "--all"])
        run(
            [
                *compose,
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "import urllib.request; "
                "print(urllib.request.urlopen('http://127.0.0.1:8000/ready', "
                "timeout=3).read().decode())",
            ]
        )
    elif args.command in {"seed", "purge"}:
        run([*compose, "exec", "-T", "api", "omniagent", args.command])
    else:
        run([*compose, "--profile", "test", "build", "test", "web-test"])
        if args.command == "test":
            run(
                [
                    *compose,
                    "--profile",
                    "test",
                    "run",
                    "--rm",
                    "test",
                    "python",
                    "-m",
                    "pytest",
                    "--basetemp",
                    "/tmp/pytest",  # noqa: S108 - private tmpfs in an ephemeral test container
                    "-p",
                    "no:cacheprovider",
                    "--cov=omniagent",
                    "--cov-fail-under=80",
                    "--cov-report=xml:/reports/coverage.xml",
                    "--junitxml=/reports/junit.xml",
                ]
            )
            run([*compose, "--profile", "test", "run", "--rm", "web-test"])
        else:
            run(
                [
                    *compose,
                    "--profile",
                    "test",
                    "run",
                    "--rm",
                    "test",
                    "omniagent",
                    args.command,
                    "--output",
                    "/reports/" + args.command,
                ]
            )


if __name__ == "__main__":
    main()
