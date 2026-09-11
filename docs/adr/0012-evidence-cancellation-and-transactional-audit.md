# ADR 0012: Complete evidence units, cooperative cancellation and atomic audit

Status: accepted

## Context

A substring check could accept a claim after its negation or condition was removed.
The graph's advisory lock also prevented a running session from accepting cancellation,
and configuration/account audit writes did not consistently share the mutation transaction.

## Decision

Treat each complete retrieved evidence unit as selectable data and reconstruct claims on
the server. Reject partial selections, including extracts that omit adjacent exceptions.
Keep the frozen v1 dataset and introduce v2 with the current contract; do not rewrite old reports.

Commit cancellation through a short row transaction. Check authority and cancellation at
subsequent execution boundaries and preserve cancelled status when a late worker returns.
Already dispatched effects may complete; retain their receipts and audit instead of claiming rollback.

Append configuration and account audit in the caller's transaction. Record stable hashes,
changed field names and versions; no raw Prompt, password or credential values.

Preserve query order, case and punctuation in the evidence-cache key. Allow only explicit
whole-query aliases and change the cache namespace version to invalidate earlier keys.

## Consequences

Extractive answers can be longer and may reject valid paraphrases. Chunk selection does not
prove whole-document semantics. Cancellation is cooperative and bounded by external-call
timeouts. Audit availability is required for sensitive mutations to commit.

The optional fixed preflight workflow demonstrates dependent read → policy lookup → write
approval without a general planning loop. Its object binding must survive recovery and editing.
