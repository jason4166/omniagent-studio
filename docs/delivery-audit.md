# v1 engineering scope and audit

Baseline: `5c92f945afe92ba09928ddecbffd9fdb5d338918`. Delivery branch: `codex/v1-delivery`.

Sources: project blueprint, final engineering acceptance checklist and Day15–Day30 engineering
requirements. The user's delivery brief makes controlled OpenAPI import, MCP server and client,
OpenTelemetry, Profile import/export, comparison charts, provider fallback and semantic cache
required. Teaching, personal assessment and private progress documents are outside this work.

Existing reusable components: Pydantic configuration, Provider protocols, deterministic FakeLLM,
tool Registry and JSON Schema validation, PostgreSQL repositories, document ingestion and chunks,
hybrid retrieval/RRF, citation identity/namespace/claim validation and bounded graph regression tests.
Audit baseline command: `uv run pytest`; result before changes: 396 passed, 10 database tests skipped.

Delivery sequence and evidence ownership:

| Milestone | Scope | Evidence |
| --- | --- | --- |
| A | durable sessions, context, approval/RBAC, idempotency, audit | context and durable-session tests, ADR 0004 |
| B | fixed HTTP connectors, local MCP, OpenAPI subset, presets/seed | adapter contracts and preset integration |
| C | typed API client, Vue administration/chat, SSE replay | frontend gates and browser workflows |
| D | security, telemetry, eval, reliability, fallback/cache | versioned datasets and generated reports |
| E | clean Docker boot, CI, public docs, release candidate | clean-room acceptance and release manifest |

Each milestone must pass its applicable full backend and integration gates before its local
commit. Release metrics are generated from current runs, not inferred from old reports.
Protected untracked files and private learning documents remain excluded from edits and staging.
There is no authorization for a remote push, PR, merge or release.
