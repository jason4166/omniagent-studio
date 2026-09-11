# Observed failures, limits and next changes

These limits are part of the v1 release evidence, not omitted acceptance cases.

| Observation | Evidence and response |
| --- | --- |
| The hosted image audit treated the private secret-directory path as a secret value | The exact `OMNIAGENT_SECRET_DIR` reference is excluded from literal-secret matching; credential values remain scanned. The regression includes both the reference and a leaked synthetic password. |
| A substring claim could omit negation or adjacent conditions | Current grounding requires the complete retrieved evidence unit. Frozen v1 partial-excerpt labels remain historical; v2 records the stricter contract. |
| Cancellation contended with the running graph lock | Cancellation now commits independently and is checked at execution boundaries; a previously dispatched effect may finish and remains recorded. |
| A concurrent browser approval was counted as an unauthorized write by an HR evaluation case | The evaluator used a database-wide receipt delta. Protocol v3 attributes receipts to the actual case session and execution identities, and checks the evaluator's decision key. Separate regressions retain detection of pending, rejected and missing-approval writes. |
| New tests passed on Windows but failed in the clean Linux image | Historical schema compatibility now uses small committed fixtures instead of release-document paths absent from the test image. The new grounding dataset hash is pinned to Git's LF bytes; the frozen labels are unchanged. |
| A CI-style UID could not write coverage state in the image-owned application directory | Reproduced with non-root UID 1001. Coverage now writes to the operator-owned report bind mount; application ownership stays restricted. |
| A paced restart changed the API address and nginx kept its old DNS answer | The proxy now uses Docker's internal resolver with bounded DNS validity, and Web health checks API readiness. Failed acceptance also preserves evidence if cleanup cannot reach the API. |
| A fresh Windows clone changed frozen dataset bytes to CRLF | Two legacy hash checks caught the drift (573 other tests passed). Git attributes now preserve LF for text in every checkout; the original frozen labels and expected hash are unchanged. |
| A nested development cache could enter an application build | Image comparison exposed a cache below the source tree. Docker excludes caches at every depth; image audit rejects Git/cache directories. Clean-clone images contained only public application inputs. |
| SSE refresh could overwrite an in-progress approval edit | Browser repetition exposed the race. Drafts now survive refresh, stale edit versions cannot submit, and obsolete session refresh responses are discarded. Two deterministic component cases cover unchanged and changed server versions. |
| Earlier answers lost their citation buttons after another turn | Citations now persist with each history message and are tested after another answer and browser reload. Draft text alone is not used to reconstruct citation authority. |
| Held-out `hr-08`, “hotel nightly limit”, safely abstains | Fake lexical matching does not equate “hotel” and “Hotels”. The case remains in the v2 dataset with its original label. A separately versioned morphology/retrieval experiment is next. |
| Historical three-query chat-only smoke rejected an HR paraphrase | That rc.1 report stays immutable. Current real mode uses real vectors, complete evidence units and a separately frozen live v2 dataset; see the current verification record for observed results. |
| Environment-backed Docker secrets failed in a read-only service | Reproduced in the first clean real build. rc.3 mounts private file-backed secrets and restores read-only API/seed filesystems; application files remain root-owned and non-writable to UID 10001. Secret values do not enter YAML, images or the browser. |
| A previous HR answer made a later out-of-domain question route to clarification | First real multi-turn acceptance failed. Routing now explicitly selects operations for the latest request and leaves refusal to grounding; three consecutive real two-turn checks passed before full acceptance was repeated. |
| Small latency differences vary between repeats | The historical SQL experiment is linked from the verification index. New same-revision runs measure repeatability; additional safety checks can add queries, and no production throughput/SLA claim follows from this workload. |
| Debian HTTP package fetch timed out during container validation | Container test builds use the same official Debian source over HTTPS with bounded retries. Base image transport uses pinned upstream artifacts from GHCR / Google cache. Network access is still required on a cold machine. |

## Deliberate boundaries

- Authentication uses independent UUID accounts, Argon2id passwords and revoked-on-change session cookies. Administrators assign roles and Profile grants. No public registration, MFA, email password recovery, SSO or organization tenancy is included. The original shared demo identities were unsuitable for public access and have been removed from serving paths.
- The fixed HTTP and MCP catalog can be reconfigured only within administrator-approved contracts. OpenAPI import supports a constrained GET-query / POST-JSON subset and cannot register arbitrary network targets or executable commands.
- All writes target a synthetic local ledger. Effect-plus-receipt atomicity and approval replay do not guarantee exactly-once effects in arbitrary real external services.
- The real deployment uses actual DeepSeek chat and Zhipu multilingual vectors with PostgreSQL full text/vector RRF. The separate required offline suite uses deterministic Fake chat/hash embeddings. The small synthetic corpus and 30 live v2 cases cannot establish general domain accuracy; PostgreSQL `simple` tokenization still limits Chinese lexical matching.
- Grounding selects complete retrieved evidence units and reconstructs claims on the server. This prevents truncating negation or conditions within a unit, but does not establish general semantic entailment or guarantee that source conditions in another chunk were retrieved. This favors safe refusal and may reject a reasonable paraphrase. Emitted-citation validity must be read alongside E2E, abstention and coverage denominators.
- Context summary is bounded extractive text, not an LLM summary. Fake token accounting uses conservative UTF-8 estimates; real usage comes from provider responses. Unknown prices remain `unknown`; configured cost ceilings cannot assume unknown prices are zero.
- SSE sends validated answer fragments after grounding finishes. It exposes progress before completion but does not stream unvalidated raw model tokens. Reconnect uses durable event replay and cannot invoke a tool.
- The conservative query-normalization cache preserves word order, case and punctuation, stores only retrieval evidence and recognizes a small explicit whole-query alias list; it is not a general answer cache. It includes permission/version namespaces and revalidates current evidence on every hit.
- Metrics and circuit breakers remain bounded process-local state. Authentication, quotas, stream leases, session, approval, events, checkpoint and audit are durable in PostgreSQL. Restart clears in-process observation history; there is no telemetry warehouse. Public traffic still requires host monitoring and upstream volumetric DDoS controls.
- No OCR, image/audio/video ingestion, queues, Kubernetes, workflow canvas, CRM/ERP integration, email, payment, training or multi-Agent swarm is implemented or required by this release.

## Roadmap

1. Expand the licensed real knowledge corpus and add independently held-out multi-turn retrieval cases; preserve the current frozen datasets.
2. Expand real-provider grounded answer tests and improve supported paraphrase handling while preserving identity, support and coverage checks.
3. Add MFA or an external identity provider, persisted metrics aggregation and automated off-host backup transport when the deployment audience requires them. The current release already provides managed accounts, TLS and authenticated encrypted backups.

Any future real external write connector needs its own authorization, idempotency and fault-injection contract before it can enter the Registry.
