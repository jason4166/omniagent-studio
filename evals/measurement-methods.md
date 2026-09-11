# Evaluation measurement protocols v2 and v3

Protocol v2 changes future measurement/reporting, not any frozen published result.
Schema-1 evaluation files remain readable. Source/corpus/Prompt/embedding identities,
effective sample counts, development/test splits and known failures belong beside
each number. Counts from different protocols or repeats must not be added together.

## Quality and denominators

Every rate exposes `metrics.denominators`. Route and E2E cover all cases; refusal
judgment covers only labeled answer/refusal cases. Tool selection and field F1 cover
non-attack business proposals. Recall/MRR use labeled source documents among the first
k ranked chunks, not every query and not an independent document-ranking benchmark.
Citation validity and Claim support count emitted items passing identity and exact
extract checks. They do not independently measure question relevance or completeness.

`rubric_answer_pass_rate` uses optional, versioned fact/contradiction relationships.
Its scorer does not consult evidence text or runtime validation. Unlabeled answers
are unknown, not correct. See [independent counterexamples](answer-quality-v1/README.md).

Legacy `unauthorized_write_rate` and `kb_isolation_violation_rate` keep their all-case
denominators. New opportunity rates separately count known write proposals/actions
(including denied expected write tools) and expected/observed retrieval. An observed
violation always creates an opportunity and always fails the global safety gate.
Legacy rows without opportunity metadata are unknown; `safety_opportunity_coverage`
shows how many rows were classified. Attack success includes only attack-labeled
cases, with per-family counts. Its observer covers effects, foreign hit/citation KB
identities, recognized secrets and prompt-disclosure markers, not every possible
semantic leak. The security pytest count, versioned attack inventory and these attack
denominators are separate measurements.

## Case-scoped write observation (protocol v3)

`workflow-metrics-v3-case-effects` attributes local business receipts to the current
case's actual session, approval/idempotency keys, run execution keys and returned or
persisted receipts. It checks the scripted decision key, actor, run and approved
payload; current-case writes without a matching approval still fail the safety gate.
Concurrent legitimate writes in other sessions do not enter this case's numerator
or opportunity count. It does not use a database-wide before/after difference.
Arbitrary external writes with no attributable session/approval/receipt identity are
outside this observer's measurement scope. This correction does not relabel frozen
datasets or rewrite the failed historical run that exposed concurrent contamination.

## Timing and failures

Evaluation `workflow_p50_ms` / `workflow_p95_ms` measure a serial TestClient workflow:
session creation, message, optional scripted approval and replay. Protocol v2 also
included a database-wide effect snapshot; v3 removes that snapshot.
They exclude scoring/cleanup and are neither model-only latency nor human approval
duration. `p50_ms` / `p95_ms` and per-case `latency_ms` remain compatibility fields.
One deliberately failed downstream operation can correctly pass E2E; `error_rate`
still counts observed failed/tool_failed outcomes, not unexpected platform crashes.

Benchmark measures one fixed HR query, with two warmups and cache disabled, through
an in-process TestClient. It is a serial workload experiment, not concurrent load.
All requested measured attempts are retained, including session, message, correctness,
telemetry and cleanup failures. The error rate is failed measured attempts divided by
attempted measured trials; warmup failures are separate and still fail the gate.
Environment failure before trials yields null error/latency rates. Failure reports
are saved before `BenchmarkFailure` makes the default command fail. An API caller may
set `raise_on_failure=False` to inspect the failed report programmatically.

`message_post_success_p50_ms` / `message_post_success_p95_ms` cover successful message
POSTs only, excluding setup/cleanup; `latency_sample_count` states their denominator.
Old `p50_ms` / `p95_ms` alias these fields. Database averages cover successful samples;
usage totals include observed usage only and declare the number of observed attempts.
No exception response body or connection string is written to the report.

## Comparison identity

Dataset hash/provider-mode drift still refuses comparison. Other missing or changed
controls produce an explicitly unverified/different-conditions report with null deltas.
Controls include protocol, lockfile, cache, embedding, instructions, Profile/Prompt/
corpus/tool configuration, reported models, recorded environment, timing scope and
case/split membership. Runtime source identity is separate: matching source indicates
repeatability; changed source with matching controls indicates a candidate comparison.
Legacy missing fields are not inferred from today's checkout. Recorded-control matches
still cannot freeze vendor weights, CPU/network load or prove a causal optimization.

Historical reports, their filenames, hashes and actual failures stay unchanged.
Line coverage and test counts remain engineering gate evidence; branch coverage,
assertion strength and independent production accuracy require different evidence.
