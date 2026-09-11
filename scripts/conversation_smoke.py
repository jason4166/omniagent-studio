"""Opt-in real-model conversation acceptance against an owned loopback deployment."""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

from acceptance import API, finish_report
from ops import ROOT, compose_arguments, run


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="omniagent-secure-real")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compose_arguments(args.project, "real")
    api = API(args.base_url, ROOT / ".local/deployments" / args.project)
    threads: list[str] = []
    observations: list[dict[str, object]] = []
    started = monotonic()
    report: dict[str, object] = {
        "schema_version": 1,
        "source_commit": run(["git", "rev-parse", "HEAD"], capture=True),
        "created_at": datetime.now(UTC).isoformat(),
        "provider": "real",
        "passed": False,
        "scope": "Model-based intent, public help, clarification and approval continuation. "
        "Bounded synthetic scenarios; no claim of exhaustive language coverage.",
    }

    def create(profile: str) -> str:
        identifier = api.request("POST", "/api/sessions", {"profile_id": profile})["thread_id"]
        threads.append(identifier)
        return str(identifier)

    def message(thread: str, text: str) -> dict:
        payload = {"message": text, "request_key": uuid4().hex}
        data = api.request("POST", f"/api/sessions/{thread}/messages", payload)
        repeated = api.request("POST", f"/api/sessions/{thread}/messages", payload)
        observations.append(
            {
                "query": text,
                "status": data["status"],
                "result": data.get("result"),
                "usage": data["usage"],
                "error_code": data.get("error"),
                "replay_usage_unchanged": data["usage"] == repeated["usage"],
            }
        )
        require(data["usage"] == repeated["usage"], "A repeated message invoked work again")
        return data

    try:
        info = api.request("GET", "/api/runtime-info")
        require(info["embedding"]["provider"] == "primary", "Real deployment required")
        profiles = api.request("GET", "/api/profiles")
        require(all(p["provider_id"] == "primary" for p in profiles), "Real model required")
        for profile, greeting, question in (
            ("hr", "早呀，第一次来这里", "我刚入职，不太清楚你能帮我解决哪些事情"),
            ("support", "哈喽，能听见我说话吗", "这个助手主要是用来干嘛的呀"),
            ("sales", "你好", "你能回答什么？"),
        ):
            thread = create(profile)
            for text in (greeting, question):
                data = message(thread, text)
                result = data.get("result") or {}
                require(result.get("response_kind") == "conversation", "Social intent missed")
                require(data["usage"]["retrieval_calls"] == 0, "Help retrieved business evidence")
                require(data["usage"]["tool_calls"] == 0, "Help invoked a business tool")
                require("Please clarify" not in result["output_text"], "English fallback leaked")
                require(data["usage"]["model_calls"] == 1, "Model did not interpret this turn")
            if profile != "sales":
                continue
            incomplete = message(thread, "帮我安排一次客户回访吧")
            require(incomplete["result"]["route"] == "clarify", "Missing input was invented")
            require(not incomplete["approval_id"], "Incomplete request became an action")
            question_text = incomplete["result"]["output_text"]
            require("客户" in question_text, "Clarification did not ask for the customer")
            completed = message(thread, "客户是 C-100，备注：明天下午确认续约需求")
            require(completed["status"] == "awaiting_approval", "Follow-up context was lost")
            path = f"/api/sessions/{thread}/approvals/{completed['approval_id']}"
            approval = api.request("GET", path)
            require(approval["tool_name"] == "create_followup", "Wrong business operation")
            require(approval["arguments"]["customer_id"] == "C-100", "Customer changed")
            require(approval["arguments"]["note"] == "明天下午确认续约需求", "User note changed")
            require(completed["usage"]["tool_calls"] == 0, "Write happened before approval")
            rejected = api.request(
                "POST",
                path,
                {
                    "action": "reject",
                    "expected_version": approval["version"],
                    "decision_key": uuid4().hex,
                },
            )
            require(rejected["result"]["status"] == "rejected", "Rejection failed")
        mixed = message(create("sales"), "嗨，帮我看看客户 C-100 的资料吧")
        require(mixed["result"].get("tool_name") == "lookup_customer", "Greeting swallowed action")
        require(mixed["result"]["status"] == "succeeded", "Read-only lookup failed")
        # Natural assistant replies in history must not replace the JSON output contract.
        followup_thread = create("hr")
        for text in ("你好", "你好", "公司福利怎么样", "薪资待遇"):
            followup = message(followup_thread, text)
            require(followup["status"] == "completed", "HR follow-up failed after social history")
            require(followup["usage"]["tool_calls"] == 0, "HR invoked a business tool")
        require(
            followup["result"].get("response_kind") != "conversation",
            "A salary question was treated as public capability help",
        )
        report["passed"] = True
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        raise
    finally:
        report["observations"] = observations
        report["elapsed_seconds"] = monotonic() - started
        finish_report(api, threads, args.output, report, keep_sessions=False)


if __name__ == "__main__":
    main()
