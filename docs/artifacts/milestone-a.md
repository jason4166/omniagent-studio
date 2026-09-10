# Milestone A validation

Validated on 2026-09-10 with the locked Python 3.12 environment and a separate PostgreSQL/pgvector
test database. This is an engineering gate record, not a v1 release acceptance report.

| Gate | Result |
| --- | --- |
| Full pytest, database environment enabled | 434 passed, 0 skipped; 9.38 s |
| Durable-session integration subset | 20 tests, included in full gate |
| Ruff check | passed |
| Ruff format check | passed, 114 files |
| Strict mypy | passed, 54 source/entry files |
| git diff --check | passed |
| Alembic | 91c0d7e2f301 head, applied to a new database |
| Existing grounding-v1 regression | decision accuracy 1.0; abstention accuracy 1.0 |
| Existing retrieval-v1, hybrid OR candidate | Recall@1 0.4615, @3 0.9615, @5 0.9615; MRR 0.7051 |
| Protected files | both SHA-256 checks unchanged |

The older grounding dataset deliberately contains invalid-citation and unsupported-claim negative
controls: raw citation validity is 0.75 and raw claim support is 0.50. These are not v1 end-user
answer accuracy claims. Full platform security, unified evaluation, frontend, Docker clean-room
acceptance and release packaging remain subsequent milestone gates.

Commands: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy src/omniagent` plus tracked day entrypoints, `git diff --check`,
`uv run python day13_grounding_eval.py --output-dir <temporary-output>`, and
`uv run python day12_retrieval_eval.py --text-query-operator or --artifacts-root <temporary-output>`.
Both database environment variables must target the same isolated test database for full pytest.

Ruff excludes the explicitly protected untracked demo and the existing teaching-only Markdown
guide. Four legacy Python files received formatting-only repairs so the repository gate passes.
