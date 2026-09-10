# ADR 0007 — Bounded dependencies, local traces and evidence cache

Status: accepted, 2026-09-10.

Every dependency attempt consumes a durable call reservation. Retries use exponential backoff, jitter, at most four attempts and an overall deadline; runtime policies use two attempts. Authentication, validation, permission, missing resource and bad schema failures are permanent. Selected 429/5xx/network/timeout failures are transient. Write retries require a stable idempotency key and the receiver's atomic key/payload/effect contract. A small process-local circuit breaker protects model endpoints, including a single half-open probe.

At most two administrator-configured real model providers may form a fallback chain. Fake cannot join that chain. Every attempt records its provider/model, call count and received usage; fallback is visible as `degraded`. Failed responses may still incur provider charges; reserved token counts remain durable even when actual usage is unavailable. Unknown prices are `unknown`, not zero. Fake counts UTF-8 bytes and has zero external cost. The optional `THINKING` extension is explicit server configuration for compatible endpoints, never a model-controlled request field.

OpenTelemetry uses a provider per application, ContextVars per request, and a bounded local exporter. Spans cover API, graph node, model, retrieval, embedding, database, tool and approval. SQL is fingerprinted; payloads, parameters, exception messages and hidden reasoning are excluded. All context tokens and spans close on errors. `OMNIAGENT_TRACE_EXPORTER=none` is the default; optional OTLP HTTP exports use an administrator endpoint and header reference. Langfuse uses the same OTLP adapter with its configured endpoint; there is no mandatory cloud telemetry.

Semantic caching stores evidence, not final answers or actions. Canonical bilingual aliases, case and term order can match within the same signature; negations and numeric qualifiers stay distinct. pgvector similarity is also checked. Cache keys contain the complete Profile, prompt content hash, authorized KB/source versions, model/provider, embedding/retrieval versions, tool policies, actor/role/permissions and code/Git version. A hit rechecks current policy and actual stored chunk identity/content/location before normal grounding. This deliberately conservative cache sacrifices hit rate to avoid privilege and meaning changes. It cannot execute a tool or grant approval.

The local trace window, circuit state and rate limiter reset with the API process. Durable run usage, decisions and effects do not. Multi-worker global rate limits and distributed tracing retention require external infrastructure and are outside this single-host v1 scope.

References: [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/), [Langfuse OTLP integration](https://langfuse.com/integrations/native/opentelemetry), [DeepSeek JSON output](https://api-docs.deepseek.com/guides/json_mode).
