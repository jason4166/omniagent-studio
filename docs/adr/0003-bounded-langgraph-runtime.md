# ADR 0003: Bounded LangGraph runtime and state ownership

## Status

Accepted for the Day 14 incremental implementation.

## Context

The handwritten `AgentRuntime` accumulated routing, retrieval, tools, budgets, and response
construction in one method. OmniAgent Studio needs an explicit execution graph without changing
the public `run(profile_id, thread_id, message)` contract or weakening deterministic permission,
approval, retrieval, and grounding checks.

The implementation uses `langgraph==1.2.11`. The adopted API is `StateGraph` with an
`input_schema`, explicitly registered nodes, ordinary and conditional edges, `START`, `END`,
`compile()`, `invoke()`, `stream(..., stream_mode="updates")`, and an invocation recursion limit.
No prebuilt or ReAct agent controls the workflow.

The rolling official guide and the source tagged for the installed release were checked on
2026-09-10:

- [Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Use the Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api)
- [GRAPH_RECURSION_LIMIT](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT)
- [`StateGraph` source at tag 1.2.11](https://github.com/langchain-ai/langgraph/blob/1.2.11/libs/langgraph/langgraph/graph/state.py)

The public documentation is updated continuously, so the tagged source is the version anchor for
the installed API. The local dependency and lock file both pin `1.2.11`.

## Decision

### Runtime structure

`ProfileEntryGraph` owns the compiled graph and runtime dependencies. Provider clients,
repositories, retrievers, the tool registry, and their database resources remain object
dependencies. They are never stored in graph state.

The public `AgentRuntime.run(profile_id, thread_id, message)` method remains the compatibility
boundary. A trusted construction-time `hit_retriever` enables graph execution. Graph failures do
not fall back to legacy string retrieval because fallback could bypass grounding validation.
Legacy string retrieval remains available only when graph mode was not configured; it cannot
manufacture citation provenance.

The current production graph is acyclic. Its compiled structure is exported to
`docs/artifacts/day14/current-graph.mmd`. The graph has these nodes:

- `load_profile` loads a trusted profile snapshot and initializes per-run state.
- `guard_input` validates profile presence, identity, and enabled state.
- `prepare_decision` loads the trusted prompt and budget and builds the routing request.
- `decide` obtains and validates a semantic route proposal from the LLM.
- `prepare_tool` converts only validated tool name and arguments into a platform-owned call.
- `execute_tool` delegates schema, profile, role, approval, and tool-budget enforcement to the
  deterministic tool registry.
- `retrieve` queries only the profile-authorized knowledge bases and builds a checked
  `ContextPack`.
- `generate_answer` asks the LLM for a structured grounding proposal from authorized evidence.
- `validate_answer` applies deterministic citation, authorization, claim-support, and conflict
  validation.
- `respond` is the single result-construction exit for success, rejection, and failure.

`respond` always reaches `END`. Conditional routes also send invalid, rejected, exhausted, and
empty-evidence states to `respond`. `GraphRecursionError` is handled outside the graph and mapped
to a stable result without exposing partial candidate output.

### State ownership

`EntryState` is a `TypedDict`: it gives static field constraints but does not perform runtime
validation. Pydantic models revalidate security-sensitive snapshots at deterministic boundaries.
The state must remain JSON serializable.

Input identity fields are written only by the caller-facing graph input. Artifact fields have a
designated producer. Shared control fields are updated by the nodes that perform the corresponding
transition or consume the corresponding resource.

| State field | Authoritative writer or writers | Principal readers | Meaning |
| --- | --- | --- | --- |
| `profile_id`, `thread_id`, `message` | graph input | all relevant nodes | Immutable request identity and user data |
| `resource_budget` | `load_profile` from construction-time policy | inspection and serialization | Requested token and cost limits |
| `profile` | `load_profile` | guards, tool, retrieval, grounding | JSON profile snapshot; never a repository object |
| `budget` | `prepare_decision` | model, tool, and retrieval nodes | JSON business-budget snapshot |
| `request` | `prepare_decision` | `decide` | Validated routing request data |
| `decision` | `decide` | conditional route, tool preparation, retrieval, response | Validated LLM route proposal |
| `tool_call` | `prepare_tool` | `execute_tool`, `respond` | Platform-owned call identity plus validated candidate arguments |
| `tool_result` | `execute_tool` | `respond` | Deterministic registry result |
| `context_pack` | `retrieve` | retrieval route, answer generation, validation, response | Authorized, identity-checked evidence only |
| `proposal` | `generate_answer` | `validate_answer` | Untrusted model candidate; never directly emitted |
| `grounding_decision` | `validate_answer` | `respond` | Deterministic decision that authorizes or rejects output |
| `result` | `respond` | public `run` boundary | Validated external `RuntimeResult` data |
| `status`, `error_code` | transition nodes | conditional routes and `respond` | Current stage and stable classified failure |
| `graph_steps_used` | every executed node | diagnostics and tests | Observable node count; not the framework recursion counter |
| `business_steps_used` | `decide`, `retrieve`, `execute_tool`, `generate_answer` | resource-consuming nodes | Cumulative business operations for this run |
| `model_calls_used` | `decide`, `generate_answer` | model nodes | Cumulative attempted model calls for this run |
| `tool_calls_used` | `execute_tool` | `execute_tool` | Cumulative controlled tool execution attempts |
| `reported_total_tokens` | model nodes | inspection and serialization | Cumulative provider-reported tokens, or unknown after incomplete usage |
| `reported_cost_microusd` | model nodes | inspection and serialization | Unknown after a model call until pricing exists |

Every run starts at `load_profile`, which clears prior artifacts and resets counters. A future retry
edge must return to a stage node rather than `load_profile`; otherwise it would reset the run budget.
Result-producing nodes clear their previous artifact before an attempt so stale candidates cannot
survive a failed retry.

### Deterministic control boundaries

- The model can propose only `direct`, `retrieve`, `tool`, or `clarify`; Pydantic rejects unknown
  routes and incompatible route fields.
- Model output cannot write profile scope, state counters, budgets, actor role, approval state,
  call identity, or grounding decisions.
- Retrieval receives a copy of the profile-authorized knowledge-base list. Every returned hit is
  checked before context-length budgeting can hide an unauthorized or inconsistent hit.
- A write tool remains an approval-required rejection placeholder. Model text cannot grant
  approval.
- Candidate answers reach external output only through `validate_answer` and `respond`.
- Documents remain untrusted context data and cannot change permissions or execution policy.

### Budgets and termination

Business limits independently bound attempted model calls, tool calls, and business steps. Counts
increase at the controlled call boundary, including failed or rejected attempts.

The LangGraph recursion limit is a separate framework backstop for accidental cycles. It does not
replace business budgets and cannot interrupt a single node blocked inside a provider; provider
timeouts remain necessary.

`ResourceBudget` reserves request-wide `max_total_tokens` and `max_cost_microusd` interfaces.
Provider-reported usage is accumulated only when complete and internally consistent. Missing usage
makes the request total unknown instead of zero. Pricing and predictive token reservation are not
implemented on Day 14, so any configured finite token or cost limit fails closed before the first
model call with `resource_budget_unavailable`. Actual latency, token, and cost reporting remains a
Day 23 concern.

## Consequences

- The control flow can be inspected and tested by node path as well as final output.
- Profiles reuse one graph while selecting different prompts, tools, knowledge bases, and budgets.
- State snapshots are portable JSON data and contain no live clients, sessions, connections,
  credentials, or locks.
- Existing callers keep the same method signature and `RuntimeResult` model.
- Enabling graph mode is an explicit construction decision while legacy string retrieval exists.
- The production graph contains no retry cycle yet. Cycle tests deliberately inject one to prove
  the framework hard limit and partial-output suppression.
- Day 14 does not add checkpointers, durable resume, live human approval, real pricing, or a
  multi-agent workflow.

## Rejected alternatives

- Do not use a prebuilt agent with hidden control flow.
- Do not put Provider clients, SQLAlchemy sessions, database connections, or locks in state.
- Do not let prompt text enforce permissions, approval, budgets, citation validity, or claim
  support.
- Do not silently enable a configured resource limit that cannot actually be enforced.
- Do not fall back to an ungrounded legacy result after graph rejection or failure.
- Do not fabricate source locators for legacy string retrieval.
