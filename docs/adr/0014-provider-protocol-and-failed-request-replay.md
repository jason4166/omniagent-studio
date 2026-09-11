# ADR 0014: Explicit structured-output protocol and failed-request replay

Status: accepted, 2026-09-11.

A real HR conversation returned a successful HTTP response containing only spaces,
before retrieval. Replaying the same history reproduced the problem. Combining the
leading system instructions improved an initial probe, but a longer conversation
still failed. Prompt arrangement alone is therefore insufficient evidence of a fix.

The real Compose configuration now selects DeepSeek's Responses API explicitly,
passing the JSON Schema through `text.format` and `reasoning.effort=none`. This reuses
the existing Responses adapter. The generic routing `args` object is incompatible
with this provider's strict schema subset (a direct probe returned HTTP 400), so
this deployment uses `strict=false`. Server-side JSON Schema, Pydantic, permission,
evidence and approval checks remain authoritative. This is not a claim of native
strict-schema guarantees or universal model reliability.

A full conversational smoke subsequently exposed another failure: after a natural
language refusal, the Responses endpoint returned that same prose instead of JSON.
Adding the JSON contract alone did not fix the exact-history probe. The durable
planner now receives prior turns as an explicitly untrusted JSON history block,
preserving their roles and order as data, followed by the current user request.
Stored chat history and browser presentation remain unchanged. Both protocol adapters
append the same explicit JSON output contract. Context trimming and reservations count
the serialized history wrapper and escaping before dispatch. This separates the
planner's output format from the assistant's previous visible answer style.

Operators select `OMNIAGENT_PROVIDER_API=responses` or `chat_completions`; no hostname
heuristic chooses the protocol. Unconfigured installations retain Chat Completions.
Responses accepts optional `OMNIAGENT_PROVIDER_SCHEMA_STRICT=true|false` (default true)
and `OMNIAGENT_PROVIDER_REASONING_EFFORT=none|low|high|max`. Chat accepts the existing
`OMNIAGENT_PROVIDER_THINKING=enabled|disabled`. Cross-protocol options are rejected.
The `OMNIAGENT_FALLBACK_*` equivalents independently configure an explicit secondary
provider. Protocol options enter cache namespaces and evaluation manifests.

Only visible output text is consumed; hidden reasoning is not an answer. Requests
remain stateless (`store=false`), bounded by the original timeout and output budget.
Invalid model output fails closed, without schema-error retry or Fake fallback.
Received usage and attempt reservations are retained even when validation fails.

A repeated message request key must return its recorded failed state without model
or tool work. Retrying execution requires the explicit resume endpoint, which keeps
the same run budget and rechecks current permissions. This separates transport
replay from a deliberate recovery attempt.

Delivery requires both frozen regressions and new exploratory conversations on the
real deployment. Fixed scripts cannot establish that all natural-language inputs
work. New failures are preserved as regressions; acceptance reports state their scope.

References: [DeepSeek JSON mode](https://api-docs.deepseek.com/guides/json_mode/),
[Responses API](https://api-docs.deepseek.com/api/create-response/).
