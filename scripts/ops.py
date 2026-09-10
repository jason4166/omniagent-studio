"""Portable, explicitly scoped Docker operations. Requires only Python, Git and Docker."""

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compose_arguments(project: str, mode: str = "fake") -> list[str]:
    if not re.fullmatch(r"omniagent-(v1|real|clean|ci|test)[a-z0-9-]*", project):
        raise ValueError("Only explicitly scoped OmniAgent project names are accepted")
    result = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.yaml")]
    if mode == "real":
        result += ["-f", str(ROOT / "compose.real.yaml")]
    elif mode != "fake":
        raise ValueError("Unknown runtime mode")
    return result


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
            "eval-real",
            "benchmark",
            "seed",
            "purge",
        ],
    )
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument("--project")
    parser.add_argument("--confirm-reset")
    args = parser.parse_args()
    if args.project is None:
        args.project = "omniagent-real" if args.mode == "real" else "omniagent-v1"
    if args.mode == "real" and args.command in {"test", "eval", "benchmark"}:
        parser.error("Offline gates require --mode fake with a separate test project/database")
    if args.command == "eval-real" and args.mode != "real":
        parser.error("Live evaluation requires --mode real and configured credential references")
    try:
        compose = compose_arguments(args.project, args.mode)
    except ValueError as exc:
        parser.error(str(exc))
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
    elif args.command == "eval-real":
        run([*compose, "--profile", "evaluation", "build", "real-eval"])
        run([*compose, "--profile", "evaluation", "run", "--rm", "real-eval"])
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
