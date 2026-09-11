"""Opt-in live ingestion/query proof using only owned disposable local test rows."""

import argparse
import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
from acceptance import API
from ops import ROOT, compose_arguments, run


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--project", default="omniagent-secure-real")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    private = ROOT / ".local" / "deployments" / args.project
    os.environ["OMNIAGENT_SECRET_DIR"] = str(private)
    api = API(args.base_url, private)
    compose = compose_arguments(args.project, "real")
    identifier = "live-upload-" + uuid4().hex
    created: dict[str, object] = {"id": identifier, "kb": False, "profile": False}
    thread = None
    report: dict[str, object] = {
        "schema_version": 1,
        "source_commit": run(["git", "rev-parse", "HEAD"], capture=True),
        "provider": "real",
        "passed": False,
    }
    started = perf_counter()
    with httpx.Client(
        base_url=api.base,
        headers={"Origin": api.base},
        timeout=45,
    ) as client:
        account = json.loads((private / "admin.json").read_text(encoding="utf-8"))
        authenticated = (
            client.post(
                "/api/auth/login",
                json={"username": account["username"], "password": account["password"]},
            )
            .raise_for_status()
            .json()
        )
        client.headers["X-CSRF-Token"] = authenticated["csrf_token"]
        try:
            info = client.get("/api/runtime-info").raise_for_status().json()
            require(info["embedding"]["provider"] == "primary", "Live embedding is required")
            client.post(
                "/api/knowledge-bases",
                json={"knowledge_base_id": identifier, "name": "Disposable live ingestion proof"},
            ).raise_for_status()
            created["kb"] = True
            document = "临时设备借用规则：每台笔记本电脑押金为 300 元。归还完好设备后全额退还押金。"
            uploaded = (
                client.post(
                    f"/api/knowledge-bases/{identifier}/sources",
                    files={"file": ("equipment.txt", document.encode("utf-8"), "text/plain")},
                )
                .raise_for_status()
                .json()
            )
            require(uploaded["status"] == "imported", "Upload must create a real index")
            repeated = (
                client.post(
                    f"/api/knowledge-bases/{identifier}/sources",
                    files={"file": ("equipment.txt", document.encode("utf-8"), "text/plain")},
                )
                .raise_for_status()
                .json()
            )
            require(repeated["status"] == "duplicate", "Repeated upload must be idempotent")
            profiles = client.get("/api/profiles").raise_for_status().json()
            template = next(row for row in profiles if row["profile_id"] == "hr")
            require(template["provider_id"] == "primary", "Real planning is required")
            profile = {
                **template,
                "profile_id": identifier,
                "name": "Live upload proof",
                "knowledge_base_ids": [identifier],
                "tool_ids": [],
            }
            client.post("/api/profiles", json=profile).raise_for_status()
            created["profile"] = True
            thread = (
                client.post("/api/sessions", json={"profile_id": identifier})
                .raise_for_status()
                .json()["thread_id"]
            )
            data = (
                client.post(
                    f"/api/sessions/{thread}/messages",
                    json={
                        "message": "临时借一台电脑要交多少押金？归还后能拿回来吗？",
                        "request_key": uuid4().hex,
                    },
                )
                .raise_for_status()
                .json()
            )
            result = data["result"] or {}
            require(
                result.get("status") == "succeeded" and "300 元" in result.get("output_text", ""),
                "New document question was not answered",
            )
            citations = result["citations"]
            require(
                bool(citations)
                and all(row["knowledge_base_id"] == identifier for row in citations),
                "Citations must belong to the new isolated KB",
            )
            require(
                all(call["provider_id"] == "primary" for call in result["model_calls"]),
                "Fake cannot satisfy live proof",
            )
            located = (
                client.get(f"/api/sessions/{thread}/citations/{citations[0]['chunk_id']}")
                .raise_for_status()
                .json()
            )
            require(
                located["content"] == document, "Citation locator must return the uploaded text"
            )
            report.update(
                {
                    "passed": True,
                    "upload": uploaded["status"],
                    "repeated_upload": repeated["status"],
                    "new_profile_only_configuration": True,
                    "authorized_citations": len(citations),
                    "usage": data["usage"],
                    "reported_models": sorted({call["model_id"] for call in result["model_calls"]}),
                    "embedding": info["embedding"],
                }
            )
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            raise
        finally:
            try:
                if thread:
                    client.delete(f"/api/sessions/{thread}").raise_for_status()
                code = (
                    "import json,sys; from sqlalchemy import create_engine,delete; "
                    "from omniagent.db_models import AgentProfileRow,KnowledgeBaseRow; "
                    "v=json.loads(sys.argv[1]); "
                    "from omniagent.database import configured_database_url; "
                    "e=create_engine(configured_database_url('')); "
                    "c=e.connect(); t=c.begin(); "
                    "c.execute(delete(AgentProfileRow).where(AgentProfileRow.profile_id==v['id'])) "
                    "if v['profile'] else None; "
                    "c.execute(delete(KnowledgeBaseRow).where("
                    "KnowledgeBaseRow.knowledge_base_id==v['id'])) "
                    "if v['kb'] else None; "
                    "t.commit(); c.close(); e.dispose()"
                )
                run([*compose, "exec", "-T", "api", "python", "-c", code, json.dumps(created)])
                report["owned_rows_cleaned"] = True
            except Exception:
                report["passed"] = False
                report["owned_rows_cleaned"] = False
                raise
            finally:
                report["elapsed_seconds"] = perf_counter() - started
                args.output.mkdir(parents=True, exist_ok=True)
                (args.output / "upload-proof.json").write_text(
                    json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
                )
                print(json.dumps(report))


if __name__ == "__main__":
    main()
