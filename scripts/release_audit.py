"""Inspect the actual default Fake images and copy only public application build inputs."""

import argparse
import json
import re
from pathlib import Path

from ops import ROOT, compose_arguments, run

from omniagent.security_scan import findings, revision


def audit(project: str, output: Path, mode: str = "fake") -> dict[str, object]:
    if not re.fullmatch(r"omniagent-(v1|real|clean|ci|test)[a-z0-9-]*", project):
        raise ValueError("Only scoped local release projects may be inspected")
    if output.exists():
        raise ValueError("Use a new output directory; audit never overwrites existing exports")
    output.mkdir(parents=True)
    compose = compose_arguments(project, mode)
    expected = revision(ROOT)
    hits = []
    images = {}
    files = 0
    config = run([*compose, "config", "--format", "json"], capture=True)
    hits.extend(findings(config.encode(), "compose-config", expected))
    for service in ("postgres", "api", "mock", "web"):
        container = run([*compose, "ps", "-q", service], capture=True)
        details = json.loads(run(["docker", "inspect", container], capture=True))[0]
        image_id = details["Image"]
        metadata = json.loads(run(["docker", "image", "inspect", image_id], capture=True))[0]
        user = details["Config"].get("User", "")
        if not user or user.split(":")[0] in {"0", "root"}:
            raise RuntimeError(f"{service} container is not configured as non-root")
        image_user = metadata["Config"].get("User", "")
        if service != "postgres" and (not image_user or image_user.split(":")[0] in {"0", "root"}):
            raise RuntimeError(f"{service} application image has a root default user")
        history = run(
            ["docker", "history", "--no-trunc", "--format", "{{.CreatedBy}}", image_id],
            capture=True,
        )
        for name, value in (("image-config", metadata), ("container-config", details["Config"])):
            hits.extend(findings(json.dumps(value).encode(), f"{service}/{name}", image_id))
        hits.extend(findings(history.encode(), f"{service}/build-history", image_id))
        environment = dict(item.split("=", 1) for item in details["Config"]["Env"])
        if any(value and key.endswith("_API_KEY") for key, value in environment.items()):
            raise RuntimeError("Container configuration contains a literal provider credential")
        if service in {"api", "mock"} and environment.get("OMNIAGENT_GIT_REVISION") != expected:
            raise RuntimeError("Running image does not match the checkout source revision")
        images[service] = {"image_id": image_id, "runtime_user": user, "image_user": image_user}
        paths = (
            ["/app/src", "/app/presets", "/app/migrations"]
            if service in {"api", "mock"}
            else ["/usr/share/nginx/html"]
            if service == "web"
            else []
        )
        for index, path in enumerate(paths):
            destination = output / f"{service}-{index}"
            run(["docker", "cp", f"{container}:{path}", str(destination)])
            for item in destination.rglob("*"):
                if item.is_symlink():
                    raise RuntimeError("Export unexpectedly contains an application symlink")
                if not item.is_file():
                    continue
                relative = item.relative_to(output).as_posix()
                if set(item.relative_to(destination).parts) & {
                    ".git",
                    ".uv-cache",
                    ".venv",
                    ".pytest_cache",
                    ".mypy_cache",
                    ".ruff_cache",
                    "__pycache__",
                }:
                    raise RuntimeError("A local cache or repository directory entered the image")
                if item.name.startswith(".env") or item.suffix in {".pem", ".key", ".pfx"}:
                    raise RuntimeError("Unexpected credential file in public application image")
                hits.extend(findings(item.read_bytes(), relative, image_id))
                files += 1
    report: dict[str, object] = {
        "schema_version": 1,
        "source_commit": expected,
        "project": project,
        "mode": mode,
        "passed": not hits,
        "images": images,
        "application_files_scanned": files,
        "finding_count": len(hits),
        "findings": hits,
        "scope": (
            "Resolved Compose configuration, running container and image configuration, build "
            "history, exported application source, presets, migrations and compiled web assets. "
            "Base operating-system and third-party dependency files are not application secret "
            "scan targets. The separate Git scanner checks all reachable source history."
        ),
    }
    (output / "image-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="omniagent-v1")
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.project, args.output, args.mode)
    print(json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
