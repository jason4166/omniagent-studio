# ADR 0004: Live inference, credential references and isolated embedding indexes

Status: accepted, 2026-09-11.

The résumé deployment must exercise live natural-language planning and semantic
retrieval. An offline Fake routing fixture and hash embedding can validate controls
but cannot substantiate model quality. We retain the mandatory deterministic CI suite
and add an explicitly selected real deployment using the same Runtime.

The real deployment uses DeepSeek chat and Zhipu embedding-3 at 1024 dimensions.
Operator environment variables supply Docker Compose secrets, mounted into only API,
seed and opt-in evaluation services as needed. Profiles store `primary` and a model
name; neither clients nor secret values enter the database, checkpoints, frontend,
Compose configuration output or images. No Fake fallback is permitted in a real chain.
Optional real fallback remains an explicit operator configuration.

An embedding index identity includes provider reference, model, dimension and a hash
of the configured endpoint. Ingestion, vector queries and semantic cache manifests use
that identity. A KB with another model fails closed. Switching modes uses a separate
database/volume; seed refuses to silently replace existing Fake Profiles. Model changes
require a new index and a deliberate Profile change. We do not erase an old index.

Embedding requests use bounded batches, typed errors, at most two transient attempts
and one deadline across a batch operation. Invalid indices, authentication and malformed
schemas are not retried. Ingestion commits only after all vectors validate. Routing sees
only allowed tool contracts, including transport; missing required business arguments
cause clarification. Grounded claims must quote exact source excerpts, allowing the
server to enforce support without trusting a second model's opinion.

The tradeoff is conservative extractive answers and fail-closed behavior when documents
or indexes are incompatible. Live latency and vendor aliases can drift. Frozen real
evaluation reports keep requested names, reported aliases, actual token usage and
unknown costs explicit. Synthetic business tools remain a local sandbox, consistent
with the scope excluding real CRM, email, payment or other external writes.
