"""Small explicitly requested real-provider run using synthetic public seed data only."""

import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from omniagent.application import create_app
from omniagent.connectors import build_adapters, build_registry, catalog
from omniagent.db_models import AgentProfileRow
from omniagent.eval_platform import EvalDataset, EvalRun, score_case, summarize, write_report
from omniagent.identity import authenticate
from omniagent.local_services import local_mock
from omniagent.postgres_repositories import SqlAlchemyAgentProfileRepository
from omniagent.presets import seed
from omniagent.security_scan import revision
from omniagent.semantic_cache import manifest
from omniagent.session_rows import EffectRow
from omniagent.session_store import digest


def real_baseline(database_url: str, output: Path) -> EvalRun:
    if not all(
        os.environ.get("OMNIAGENT_PROVIDER_" + field) for field in ("API_KEY", "BASE_URL", "MODEL")
    ):
        raise ValueError("Real baseline requires explicit API_KEY, BASE_URL and MODEL references")
    dataset = EvalDataset.model_validate_json(
        Path("evals/v1/cases.json").read_text(encoding="utf-8")
    )
    selected = [
        next(case for case in dataset.cases if case.case_id == identifier)
        for identifier in ("hr-01", "support-01", "sales-01")
    ]
    results = []
    versions: dict[str, object] = {
        "git_commit": revision(Path.cwd()),
        "uv_lock_hash": digest(Path("uv.lock").read_text()),
        "cache_enabled": False,
    }
    profiles: dict[str, object] = {}
    actor = authenticate("Bearer local-demo-admin")
    with local_mock(database_url) as port:
        app = create_app(database_url, mock_port=port, cache_enabled=False)
        store = app.state.store
        definitions = catalog("127.0.0.1", port)[0]
        seed(store, definitions)
        registry = build_registry(store, build_adapters("127.0.0.1", port), definitions)
        with TestClient(app, headers={"Authorization": "Bearer local-demo-admin"}) as client:
            for case in selected:
                identifier = "real-baseline-" + uuid4().hex
                profile = store.profile(case.profile_id, actor).model_copy(
                    update={
                        "profile_id": identifier,
                        "provider_id": "primary",
                        "model": os.environ["OMNIAGENT_PROVIDER_MODEL"],
                    }
                )
                with store.factory.begin() as db:
                    SqlAlchemyAgentProfileRepository(db).save(profile)
                thread_id = None
                try:
                    profiles[case.profile_id] = manifest(store, profile, actor, registry)
                    with store.factory() as db:
                        before = set(db.scalars(select(EffectRow.idempotency_key)))
                    started = perf_counter()
                    created = client.post("/api/sessions", json={"profile_id": identifier})
                    created.raise_for_status()
                    thread_id = created.json()["thread_id"]
                    response = client.post(
                        f"/api/sessions/{thread_id}/messages",
                        json={"message": case.query, "request_key": uuid4().hex},
                    )
                    response.raise_for_status()
                    scored = score_case(
                        case.model_copy(update={"profile_id": identifier, "role": "admin"}),
                        response.json(),
                        {},
                        store,
                        (perf_counter() - started) * 1000,
                        before,
                    )
                    results.append(scored.model_copy(update={"profile_id": case.profile_id}))
                finally:
                    if thread_id:
                        client.delete(f"/api/sessions/{thread_id}").raise_for_status()
                    with store.factory.begin() as db:
                        db.execute(
                            delete(AgentProfileRow).where(AgentProfileRow.profile_id == identifier)
                        )
    versions["profiles"] = profiles
    run = EvalRun(
        run_id=str(uuid4()),
        created_at=datetime.now(UTC).isoformat(),
        dataset_version=dataset.dataset_version + "-real-smoke-3",
        dataset_hash=digest([case.model_dump(mode="json") for case in selected]),
        provider_mode="real",
        variant="real-provider-smoke",
        versions=versions,
        metrics=summarize(results),
        safety_gates={
            "unauthorized_write_zero": not any(row.unauthorized_write for row in results),
            "kb_isolation_zero": not any(row.kb_isolation_violation for row in results),
        },
        results=results,
    )
    write_report(run, output)
    return run
