# Day 14 acceptance audit — 2026-09-10

Status: Day 14 engineering and closeout are complete. P0 evidence is 5/6 because the learner has
not independently drawn and explained the graph without looking at the code.

## Delivered behavior

- Pinned and verified `langgraph==1.2.11`; the adopted Graph API is recorded in ADR 0003 with
  official documentation and tagged-source references.
- Kept the two-node, one-conditional-edge learning graph in `minimal_graph.py` and its executable
  entry point in `day14_graph_demo.py`.
- Added the explicit ten-node `ProfileEntryGraph`: `load_profile`, `guard_input`,
  `prepare_decision`, `decide`, `prepare_tool`, `execute_tool`, `retrieve`, `generate_answer`,
  `validate_answer`, and `respond`.
- Preserved `AgentRuntime.run(profile_id, thread_id, message)`. Supplying a trusted
  `hit_retriever` selects graph mode; existing callers can keep the same invocation.
- Exported `current-graph.mmd` from the compiled graph and recorded one Fake-provider retrieval
  path in `knowledge-walkthrough.json`.

## Deterministic boundaries

- State contains JSON-compatible snapshots and counters; provider clients, repositories,
  SQLAlchemy sessions, connections, locks, and credentials remain runtime dependencies.
- The model can propose a route, tool arguments, or answer candidate. It cannot set permissions,
  approval, budgets, counters, call identity, citation validity, or the final grounding decision.
- Retrieval preserves `KB filter → match/distance/rank → deterministic order → top-k`; all returned
  hit identities are checked before context budgeting.
- Write tools still stop with `approval_required`. No model field can grant approval.
- Day 13 citation, authorization, claim-support, and conflict checks run in
  `validate_answer`; rejected candidates never reach the external result.
- Graph rejection or failure never falls back to legacy ungrounded retrieval.

## Budgets and termination

- Business budgets bound attempted model calls, tool calls, and business steps. Attempts are
  counted even when providers, retrieval, or tools fail.
- The compiled graph also has `recursion_limit=9`; `GraphRecursionError` maps to the stable
  `graph_step_limit_exceeded` result and suppresses partial candidates.
- `ResourceBudget` reserves request-wide `max_total_tokens` and `max_cost_microusd` fields. Missing
  or inconsistent provider usage becomes unknown rather than zero.
- Predictive token reservation and pricing are not implemented on Day 14. A configured finite
  token or cost limit therefore fails closed before the first model call with
  `resource_budget_unavailable`; real cost reporting remains scheduled for Day 23.
- The production graph is acyclic. The hard-limit test injects a real cycle only to prove the
  backstop and partial-output suppression.

## Verification

- Full pytest with PostgreSQL enabled: `406 passed` in 3.41 seconds. Pytest emitted one cache-only
  ACL warning for `.pytest_cache`; the explicit writable `--basetemp` worked and no test failed.
- Required paths cover direct, clarify, retrieve, read tool, write approval, invalid and unknown
  model output, business budget exhaustion, resource budget fail-closed behavior, tool and
  retrieval failures, an injected cycle, grounding rejection, unauthorized citations, and the
  unchanged public Runtime call.
- PostgreSQL container: healthy; PostgreSQL `16.15`; pgvector `0.8.6`; Alembic
  `8f6d2e1c4b7a`; 11 retained chunks, all 1024 dimensions.
- Ruff check, the 11-file Day 14 format check, mypy over 35 source files, Alembic check, compiled
  Mermaid comparison, `git diff --check`, frozen-file scope checks, and protected-file hash checks
  all passed.
- No real provider was called. No key value was read, printed, logged, or stored.

## Scope and evidence

- AI implemented and tested the production changes. This is engineering delivery, not evidence of
  independent learner coding.
- The learner-independent P0 item remains the ability to draw the graph and explain, node by node,
  why each node exists and whether it uses an LLM. It is intentionally not marked complete by this
  audit.
- Day 14 is published as the feature commit containing this audit on
  `codex/day2-day3-python-foundations`. Its resulting SHA and remote verification are recorded in
  the ignored local state documents after Git publication. No PR or merge is part of Day 14.
