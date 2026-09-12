"""Portable, explicitly scoped Docker operations. Requires only Python, Git and Docker."""

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from private_config import private_directory

ROOT = Path(__file__).resolve().parents[1]


def compose_arguments(project: str, mode: str = "fake") -> list[str]:
    if not re.fullmatch(r"omniagent-(v1|real|clean|ci|test|secure)[a-z0-9-]*", project):
        raise ValueError("Only explicitly scoped OmniAgent project names are accepted")
    result = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.yaml")]
    if mode == "real":
        result += ["-f", str(ROOT / "compose.real.yaml")]
    elif mode != "fake":
        raise ValueError("Unknown runtime mode")
    return result


def run(
    arguments: list[str],
    *,
    capture: bool = False,
    timeout: int = 1200,
    stdin_text: str | None = None,
) -> str:
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
        input=stdin_text,
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
    parser.add_argument("--environment", choices=["local", "production"])
    parser.add_argument("--origin")
    parser.add_argument(
        "--port", type=int, help="Local Web port, pinned when the project is created"
    )
    parser.add_argument("--test-accounts", action="store_true")
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Start only from already loaded images; never build or pull (bootstrap/up only)",
    )
    parser.add_argument(
        "--public-preview",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable prefilled, isolated public reviewer logins; saved per deployment",
    )
    parser.add_argument(
        "--preview-profiles", help="Comma-separated Profile IDs exposed to public reviewers"
    )
    parser.add_argument("--confirm-reset")
    args = parser.parse_args()
    if args.skip_build and args.command not in {"up", "bootstrap"}:
        parser.error("--skip-build is only available with up or bootstrap")
    if (
        args.public_preview is not None or args.preview_profiles is not None
    ) and args.command not in {"up", "bootstrap"}:
        parser.error("Public preview settings can only be changed with up or bootstrap")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("Local Web port must be between 1 and 65535")
    if args.project is None:
        args.project = "omniagent-secure-real" if args.mode == "real" else "omniagent-secure-fake"
    # Validate the project before resolving any project-owned path.
    try:
        compose_arguments(args.project, args.mode)
    except ValueError as exc:
        parser.error(str(exc))
    metadata_path = private_directory(ROOT, args.project) / "deployment.json"
    saved = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    preview_enabled = (
        args.public_preview
        if args.public_preview is not None
        else saved.get("public_preview", False)
    )
    preview_profiles = (
        args.preview_profiles.split(",")
        if args.preview_profiles is not None
        else saved.get("preview_profiles", ["hr", "support", "sales"])
    )
    if (
        not isinstance(preview_enabled, bool)
        or not isinstance(preview_profiles, list)
        or not 1 <= len(preview_profiles) <= 30
        or any(
            not isinstance(item, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", item)
            for item in preview_profiles
        )
        or len(set(preview_profiles)) != len(preview_profiles)
    ):
        parser.error("Invalid public preview settings")
    os.environ["OMNIAGENT_PUBLIC_PREVIEW_ENABLED"] = str(preview_enabled).lower()
    os.environ["OMNIAGENT_PUBLIC_PREVIEW_PROFILE_IDS"] = ",".join(preview_profiles)
    args.environment = args.environment or saved.get("environment", "local")
    if saved and (args.environment != saved["environment"] or args.mode != saved["mode"]):
        parser.error("Deployment mode is pinned; use a separate project for another environment")
    if args.test_accounts and (
        args.environment != "local"
        or not args.project.startswith(("omniagent-test", "omniagent-clean", "omniagent-ci"))
    ):
        parser.error("Test accounts require an isolated local test/clean project")
    if args.mode == "real" and args.command in {"test", "eval", "benchmark"}:
        parser.error("Offline gates require --mode fake with a separate test project/database")
    if args.command == "eval-real" and args.mode != "real":
        parser.error("Live evaluation requires --mode real and configured credential references")
    try:
        compose = compose_arguments(args.project, args.mode)
    except ValueError as exc:
        parser.error(str(exc))
    origin = (
        args.origin
        or saved.get("origin")
        or os.environ.get("OMNIAGENT_PUBLIC_ORIGIN")
        or "http://127.0.0.1:" + str(args.port or os.environ.get("OMNIAGENT_WEB_PORT") or "8080")
    )
    parsed = urlsplit(origin)
    if args.environment == "production":
        if args.port is not None:
            parser.error("Production uses the HTTPS edge ports; --port is for local deployments")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            parser.error("Production requires an explicit HTTPS origin without a path")
        compose += ["-f", str(ROOT / "compose.production.yaml")]
        os.environ["OMNIAGENT_DOMAIN"] = parsed.hostname
        if args.command in {"test", "eval", "eval-real", "benchmark", "reset"}:
            parser.error("Evaluation and reset are unavailable for production deployments")
    else:
        try:
            local_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            parser.error("Invalid local origin port")
        if args.port is not None and args.port != local_port:
            parser.error("The local port must match the project's pinned origin")
        # A fresh terminal must restore the project's published port as well as its
        # authentication origin. An inherited environment must not retarget an existing stack.
        os.environ["OMNIAGENT_WEB_PORT"] = str(local_port)
    os.environ["OMNIAGENT_PUBLIC_ORIGIN"] = origin
    secret_dir = private_directory(
        ROOT,
        args.project,
        create=args.command in {"up", "bootstrap"},
        test_accounts=args.test_accounts,
        real_provider=args.mode == "real",
    )
    if args.command in {"up", "bootstrap"}:
        if saved and origin != saved["origin"]:
            parser.error("Deployment origin is pinned; migrate it explicitly before restarting")
        deployment = {
            **saved,
            "environment": args.environment,
            "origin": origin,
            "mode": args.mode,
            "public_preview": preview_enabled,
            "preview_profiles": preview_profiles,
        }
        if deployment != saved:
            temporary = metadata_path.with_suffix(".pending.json")
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(deployment, stream)
            temporary.replace(metadata_path)
    os.environ["OMNIAGENT_SECRET_DIR"] = str(secret_dir)
    os.environ["OMNIAGENT_GIT_REVISION"] = run(["git", "rev-parse", "HEAD"], capture=True)
    if hasattr(os, "getuid"):
        os.environ["OMNIAGENT_TEST_UID"] = str(os.getuid())
        os.environ["OMNIAGENT_TEST_GID"] = str(os.getgid())
    (ROOT / ".pytest-tmp-container-reports").mkdir(exist_ok=True)
    if args.command in {"bootstrap", "up"}:
        run([*compose, "config", "--quiet"])
        if not args.skip_build:
            run(
                [
                    *compose,
                    "build",
                    "migrate",
                    "mock",
                    "web",
                    *(["edge"] if args.environment == "production" else []),
                ]
            )
        run(
            [
                *compose,
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "120",
                *(["--no-build", "--pull", "never"] if args.skip_build else []),
            ]
        )
        for name in ["admin", "member", "viewer"] if args.test_accounts else ["admin"]:
            run(
                [*compose, "exec", "-T", "api", "omniagent", "account-create"],
                stdin_text=(secret_dir / (name + ".json")).read_text(encoding="utf-8"),
            )
        print(
            "Initial account file (existing passwords are never reset):", secret_dir / "admin.json"
        )
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
