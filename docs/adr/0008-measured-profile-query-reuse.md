# ADR 0008 — Reuse the Profile returned by one authorization check

Status: accepted, 2026-09-11.

The fixed 20-request Fake HR workload exposed 148 database statements per answer. The three Profile/Tool/KB lookup fingerprints each appeared 560 times, or 28 reads per request. PostgreSQL `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` showed the individual Profile lookup was cheap. A sequential scan over the tiny preset table was appropriate; adding another index would not remove the observed application round trips.

`SessionStore.load_authorized` now returns both the decoded session and the freshly authorized Profile. `guard`, the session router and citation endpoint use that pair instead of immediately fetching the same Profile again. Each graph node and dependency attempt still performs current ownership, role, enabled/version, TTL and budget validation. No permission object is cached across checks or requests.

The first candidate reduced queries from 148 to 118. P50 changed from 246.7945 to 207.37565 ms; P95 from 279.352235 to 241.90491 ms. An independent repeated candidate run measured P50 213.04285 and P95 231.683095 ms, still 118 queries. The optimization is retained. Final immutable-commit measurements are in `docs/artifacts/benchmark-*`; those reports supersede these initial observations for release metrics.

The development evaluation also identified a policy question incorrectly routed as a follow-up action. The deterministic Fake provider now prioritizes policy-question intent before configured keyword action rules, while explicit JSON proposals still undergo the normal server checks. Runtime contains no scenario-name branch. The frozen test split, including its known hotel/Hotels lexical failure, is unchanged.

The final code review additionally clamps real embedding timeouts to the parent retry deadline and preserves transient versus permanent provider errors. HTTP 501 is not retried. These changes do not introduce an external service into mandatory Fake CI.
