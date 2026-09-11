"""Real HTTP, container restart and replay acceptance; optional paced three-minute demo."""

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ops import ROOT, compose_arguments, run


class API:
    def __init__(self, base: str, credential_directory: Path) -> None:
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Acceptance only targets the local demo")
        self.base = base.rstrip("/")
        self.sessions = {}
        for admin, filename in [(False, "member.json"), (True, "admin.json")]:
            path = credential_directory / filename
            if not path.exists():
                path = credential_directory / "admin.json"
            account = json.loads(path.read_text(encoding="utf-8"))
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
            request = urllib.request.Request(  # noqa: S310 - validated loopback origin
                self.base + "/api/auth/login",
                data=json.dumps(
                    {"username": account["username"], "password": account["password"]}
                ).encode(),
                headers={"Origin": self.base, "Content-Type": "application/json"},
                method="POST",
            )
            with opener.open(request, timeout=15) as response:
                csrf = json.load(response)["csrf_token"]
            self.sessions[admin] = (opener, csrf)

    def request(
        self, method: str, path: str, payload: object = None, *, admin: bool = False
    ) -> Any:
        request = urllib.request.Request(  # noqa: S310 - constructor enforces loopback HTTP
            self.base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "X-CSRF-Token": self.sessions[admin][1],
                "Origin": self.base,
                "Content-Type": "application/json",
            },
            method=method,
        )
        with self.sessions[admin][0].open(request, timeout=45) as response:  # noqa: S310 - validated loopback
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise RuntimeError("Oversized acceptance response")
            return json.loads(body) if body else None

    def events(
        self, thread: str, *, cursor: str = "", disconnect_after: int = 0
    ) -> list[dict[str, Any]]:
        headers = {"Origin": self.base}
        if cursor:
            headers["Last-Event-ID"] = cursor
        path = f"/api/sessions/{thread}/events"
        if not disconnect_after:
            path += "?follow=false"
        request = urllib.request.Request(self.base + path, headers=headers)  # noqa: S310
        events = []
        with self.sessions[False][0].open(request, timeout=15) as response:  # noqa: S310 - validated loopback
            for raw in response:
                if len(raw) > 131072:
                    raise RuntimeError("Oversized SSE frame")
                if raw.startswith(b"data: "):
                    events.append(json.loads(raw[6:]))
                    if disconnect_after and len(events) == disconnect_after:
                        break
        return events


def finish_report(
    api: API,
    threads: list[str],
    output: Path,
    report: dict[str, object],
    *,
    keep_sessions: bool,
) -> None:
    cleanup_errors = []
    if not keep_sessions:
        for thread in threads:
            try:
                api.request("DELETE", f"/api/sessions/{thread}")
            except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                    continue
                cleanup_errors.append({"thread_id": thread, "error_type": type(exc).__name__})
    if cleanup_errors:
        report["passed"] = False
    report["cleanup_errors"] = cleanup_errors
    report["sessions_retained"] = (
        threads if keep_sessions else [entry["thread_id"] for entry in cleanup_errors]
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "acceptance.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if cleanup_errors:
        raise RuntimeError("Acceptance cleanup failed; the failure report was preserved")


def main() -> None:
    if not __debug__:
        raise RuntimeError("Acceptance assertions require normal Python mode")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--project", default="omniagent-secure-fake")
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument("--output", type=Path, default=ROOT / ".pytest-tmp-acceptance")
    parser.add_argument("--demo-seconds", type=int, default=0)
    parser.add_argument("--keep-sessions", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"omniagent-(v1|real|clean|ci|test|secure)[a-z0-9-]*", args.project):
        parser.error("Only project-scoped local containers may be restarted")
    if args.demo_seconds and not 180 <= args.demo_seconds <= 300:
        parser.error("A paced demonstration must last 180..300 seconds")
    private = ROOT / ".local" / "deployments" / args.project
    os.environ["OMNIAGENT_SECRET_DIR"] = str(private)
    api = API(args.base_url, private)
    compose = compose_arguments(args.project, args.mode)
    started = time.monotonic()
    phases: list[dict[str, object]] = []
    threads = []

    def phase(index: int, name: str) -> None:
        target = started + args.demo_seconds * index / 8
        while time.monotonic() < target:
            time.sleep(min(0.25, target - time.monotonic()))
        entry = {"phase": name, "elapsed_seconds": time.monotonic() - started}
        phases.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    def create(profile: str) -> str:
        data = api.request("POST", "/api/sessions", {"profile_id": profile})
        thread = str(UUID(data["thread_id"]))
        threads.append(thread)
        return thread

    def message(thread: str, query: str) -> dict[str, Any]:
        return api.request(
            "POST",
            f"/api/sessions/{thread}/messages",
            {"message": query, "request_key": uuid4().hex},
        )

    def effect_count(key: str) -> int:
        UUID(key)
        code = (
            "import sys; from sqlalchemy import create_engine,text; "
            "from omniagent.database import configured_database_url; "
            "engine=create_engine(configured_database_url('')); "
            "connection=engine.connect(); "
            "print(connection.scalar(text('SELECT count(*) FROM mock_effects "
            "WHERE idempotency_key=:key'), {'key':sys.argv[1]})); connection.close()"
        )
        return int(run([*compose, "exec", "-T", "mock", "python", "-c", code, key], capture=True))

    report: dict[str, object] = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source_commit": run(["git", "rev-parse", "HEAD"], capture=True),
        "project": args.project,
        "provider": args.mode,
        "passed": False,
    }
    try:
        phase(0, "health and repeatable seed")
        assert api.request("GET", "/ready")["status"] == "ready"
        profiles = api.request("GET", "/api/profiles")
        assert {profile["profile_id"] for profile in profiles} == {"hr", "support", "sales"}
        runtime_info = api.request("GET", "/api/runtime-info")
        expected_provider = "primary" if args.mode == "real" else "fake"
        assert {profile["provider_id"] for profile in profiles} == {expected_provider}
        assert runtime_info["embedding"]["provider"] == expected_provider
        report["runtime"] = runtime_info
        report["models"] = sorted({profile["model"] for profile in profiles})
        first = json.loads(run([*compose, "exec", "-T", "api", "omniagent", "seed"], capture=True))
        second = json.loads(run([*compose, "exec", "-T", "api", "omniagent", "seed"], capture=True))
        assert first == second and second["created_profiles"] == 0
        report["seed"] = second

        phase(1, "HR cited answer and evidence locator")
        hr = create("hr")
        answer = message(
            hr, "今年有多少天带薪年假？" if args.mode == "real" else "年假 leave allowance"
        )
        assert answer["result"]["status"] == "succeeded"
        citation = answer["result"]["citations"][0]
        located = api.request("GET", f"/api/sessions/{hr}/citations/{citation['chunk_id']}")
        assert located["knowledge_base_id"] == "hr-kb" and "10" in located["content"]
        report["hr_citation"] = True
        report["reported_models"] = sorted(
            {call["model_id"] for call in answer["result"]["model_calls"]}
        )

        phase(2, "HR no-evidence abstention")
        refusal = message(hr, "月球基地停车费是多少")
        assert refusal["result"]["status"] == "rejected" and not refusal["result"]["citations"]
        report["hr_abstention"] = True

        phase(3, "read-only HTTP and MCP tools")
        support = create("support")
        for query, expected in (
            ("产品查询 P-100", "lookup_product"),
            ("MCP 产品 P-200", "catalog.lookup_product"),
            ("保修查询 SN-100", "check_warranty"),
        ):
            data = message(support, query)
            assert data["status"] == "completed" and data["result"]["tool_name"] == expected
            assert data["result"]["status"] == "succeeded" and not data["approval_id"]
        report["http_and_mcp"] = True

        phase(4, "sales write proposal and persisted interrupt")
        sales = create("sales")
        pending = message(sales, "为客户 C-100 创建回访，备注：确认续约需求")
        assert pending["status"] == "awaiting_approval" and pending["usage"]["tool_calls"] == 0
        approval = str(UUID(pending["approval_id"]))
        assert effect_count(approval) == 0

        phase(5, "restart PostgreSQL mock and API; restore pending approval")
        run([*compose, "restart", "postgres", "mock", "api"], timeout=90)
        deadline = time.monotonic() + 60
        while True:
            try:
                if api.request("GET", "/ready")["status"] == "ready":
                    break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        restored = api.request("GET", f"/api/sessions/{sales}")
        assert restored["approval_id"] == approval and restored["status"] == "awaiting_approval"
        assert api.request("GET", f"/api/sessions/{hr}")["history"]
        assert api.request("POST", f"/api/sessions/{sales}/resume")["status"] == "awaiting_approval"
        report["restart_recovery"] = True

        phase(6, "edit and approve; duplicate approval produces one effect")
        path = f"/api/sessions/{sales}/approvals/{approval}"
        proposal = api.request("GET", path)
        decision = {
            "action": "edit",
            "expected_version": proposal["version"],
            "decision_key": uuid4().hex,
            "arguments": {"customer_id": "C-200", "note": "Synthetic release follow-up"},
        }
        completed = api.request("POST", path, decision)
        assert completed["status"] == "completed" and completed["result"]["status"] == "succeeded"
        assert api.request("POST", path, decision)["usage"] == completed["usage"]
        assert effect_count(approval) == 1
        report["edited_approval_single_effect"] = True

        phase(7, "SSE disconnect and cursor resume cannot repeat a write")
        partial = api.events(sales, disconnect_after=3)
        remaining = api.events(sales, cursor=partial[-1]["event_id"])
        joined = partial + remaining
        assert len({event["event_id"] for event in joined}) == len(joined)
        assert [event["sequence"] for event in joined] == list(range(1, len(joined) + 1))
        assert api.events(sales, cursor=joined[-1]["event_id"]) == []
        assert api.request("GET", f"/api/sessions/{sales}")["usage"] == completed["usage"]
        assert effect_count(approval) == 1
        rejected_thread = create("sales")
        discount = message(rejected_thread, "为客户 C-100 申请 8% 折扣，原因：年度续约")
        discount_id = discount["approval_id"]
        path = f"/api/sessions/{rejected_thread}/approvals/{discount_id}"
        proposal = api.request("GET", path)
        rejected = api.request(
            "POST",
            path,
            {
                "action": "reject",
                "expected_version": proposal["version"],
                "decision_key": uuid4().hex,
            },
        )
        assert rejected["result"]["status"] == "rejected" and effect_count(discount_id) == 0
        report["sse_replay_and_rejection"] = True

        phase(8, "review non-root services audit and final health")
        users = {}
        for service in ("postgres", "api", "mock", "web"):
            identifier = run([*compose, "ps", "-q", service], capture=True)
            user = run(
                ["docker", "inspect", identifier, "--format", "{{.Config.User}}"], capture=True
            )
            assert user and user.split(":")[0] not in {"0", "root"}
            users[service] = user
        report["container_users"] = users
        assert api.request("GET", "/api/audit", admin=True)
        assert api.request("GET", "/ready")["status"] == "ready"
        report["passed"] = True
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        report["phases"] = phases
        finish_report(api, threads, args.output, report, keep_sessions=args.keep_sessions)


if __name__ == "__main__":
    main()
