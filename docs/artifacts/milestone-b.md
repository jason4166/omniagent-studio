# Milestone B verification

Executed on 2026-09-10, using an isolated PostgreSQL/pgvector database and local HTTP/MCP
processes. No public model or business service was used.

| Gate | Observed result |
| --- | --- |
| Complete backend suite with both database variables configured | 491 passed, 0 skipped, 20.02 s |
| Ruff check / format check | Passed / 139 files formatted |
| Strict mypy | Passed, 64 source and entry files |
| git diff --check | Passed |
| Grounding regression | Decision accuracy 1.0000; abstention accuracy 1.0000 |
| Hybrid retrieval regression, OR operator | Recall@1 0.4615; @3 0.9615; @5 0.9615; MRR 0.7051 |
| Repeated preset seed | 0 additional Profiles; identical counts on repeat |
| HTTP downstream commit followed by lost response | Resume returned the original effect; no duplicate write |
| MCP | Actual SDK stdio discovery, tool call and resource read passed |

The old grounding regression deliberately contains invalid proposals: raw citation validity
0.7500 and claim support 0.5000 are not production quality scores. Unified v1 evaluation is a
later milestone. Fake byte usage and deterministic routing are explicitly synthetic.

The API tests use a real ephemeral TCP mock server, PostgreSQL persistence and all three seeded
Profiles. They exercise grounded citations, abstention, read-only HTTP/MCP tools, approval edits,
restart/replay, forged downstream calls, immutable prompts and controlled OpenAPI import.
The HTTP contract tests cover destination controls, SSRF, redirects, content/size/schema errors
and status mapping. Connectors preserve downstream idempotency keys.

Evidence commands and JUnit: `.pytest-tmp-all-b-final/junit.xml`,
`.pytest-tmp-grounding-b/report.json`, `.pytest-tmp-retrieval-b/candidate/report.json`.
These local raw files are reproducible and ignored by Git.
