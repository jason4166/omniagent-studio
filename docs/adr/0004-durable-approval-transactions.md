# ADR 0004: Durable graph, transactional authority and local idempotency

Status: accepted for v1 delivery.

The existing configuration models, tool Registry, ingestion, hybrid retrieval and deterministic
grounding validators remain shared. The v1 service compiles one bounded LangGraph for every
Profile. Legacy incremental graphs remain regression fixtures; they are not mounted as an
alternate execution API by the v1 application.

PostgreSQL is authoritative for session ownership, TTL, schema version, Profile version, consumed
budgets, approval decisions and the request replay ledger. LangGraph PostgresSaver persists node
progress with synchronous durability. It stores JSON domain data and framework checkpoint types;
Python pickle fallback and arbitrary deserialization modules are disabled. Provider objects,
connections, secrets and rendered system prompts are never included in graph state.

A session-wide PostgreSQL advisory lock serializes send/resume/decision/cancel/delete across
processes. Approval changes additionally lock rows and check an expected version and decision
payload hash. Editing means edit-and-approve: modified arguments are validated again. Every
execution reloads authorization and checks the recorded Profile/tool-policy version. A resume
payload is only a wake-up signal; it grants no permissions.

Budget reservations commit before dependency calls, so a crash cannot restore a spent allowance.
Retries after a node crash consume another reservation. Human waiting pauses the active deadline
by storing remaining time; it does not reset steps, calls or tokens. TTL continues during waiting.
Input length and conservative UTF-8 token reservation bound context, with a sliding window and
deterministic omission summary. Evidence locators and approvals remain separate durable records.
Unknown or incomplete saved schemas fail closed. Expired/deleted sessions cannot be resumed.

The mock write transaction serializes a stable operation key and atomically stores its result.
Repeated execution with the same key and payload returns that result; a different payload
conflicts. Graph checkpoint commit and business commit are separate transactions. This is
at-least-once delivery with idempotent effects, not a claim of distributed exactly-once delivery.
HTTP adapters must extend this contract to the downstream mock server before write retries.

Audit records contain actor hashes, IDs, action codes and argument/output hashes, not raw prompts
or business text. Deleting a session deletes graph checkpoints, approvals, events and request
replay data. Hash-only audit and independent business effects have separate retention semantics.
Development bearer identities are intentionally local demonstration authentication, not SSO.

Official interfaces checked against the installed packages:

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [PostgreSQL saver](https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-postgres)

Validation: `tests/test_context_policy.py` and `tests/test_durable_sessions.py` cover deterministic
context, ownership, schema/TTL/deletion, version and argument changes, cancellation, expiry,
concurrent decisions and failure before/after effects and before response publication.
