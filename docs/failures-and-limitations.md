# Observed failures, limits and next changes

These limits are part of the v1 release evidence, not omitted acceptance cases.

| Observation | Evidence and response |
| --- | --- |
| A paced restart changed the API address and nginx kept its old DNS answer | The proxy now uses Docker's internal resolver with bounded DNS validity, and Web health checks API readiness. Failed acceptance also preserves evidence if cleanup cannot reach the API. |
| A fresh Windows clone changed frozen dataset bytes to CRLF | Two legacy hash checks caught the drift (573 other tests passed). Git attributes now preserve LF for text in every checkout; the original frozen labels and expected hash are unchanged. |
| A nested development cache could enter an application build | Image comparison exposed a cache below the source tree. Docker excludes caches at every depth; image audit rejects Git/cache directories. Clean-clone images contained only public application inputs. |
| SSE refresh could overwrite an in-progress approval edit | Browser repetition exposed the race. Drafts now survive refresh, stale edit versions cannot submit, and obsolete session refresh responses are discarded. Two deterministic component cases cover unchanged and changed server versions. |
| Earlier answers lost their citation buttons after another turn | Citations now persist with each history message and are tested after another answer and browser reload. Draft text alone is not used to reconstruct citation authority. |
| Held-out `hr-08`, “hotel nightly limit”, safely abstains | Fake lexical matching does not equate “hotel” and “Hotels”. Candidate test is 32/33; the held-out labels were not rewritten. A separately versioned morphology/retrieval experiment is next. |
| Optional real Provider HR draft fails strict Claim support | Current three-query baseline is 2/3. The validator rejects `unsupported_claim`, emits no unsupported cited answer, and the real CLI exits 1. Broader real-model success is not claimed. |
| Small latency differences vary between repeats | Query count falls 148 → 118 in all candidate runs. P95 gain is small in the first run and larger in the retest. SQL roundtrip reduction is the stable finding; no throughput/SLA claim follows from this workload. |
| Debian HTTP package fetch timed out during container validation | Container test builds use the same official Debian source over HTTPS with bounded retries. Base image transport uses pinned upstream artifacts from GHCR / Google cache. Network access is still required on a cold machine. |

## Deliberate boundaries

- Authentication is `DevUserContext` with public local demonstration identities and three roles. An administrator can create Profiles; demo member/viewer access is limited to the three granted preset IDs. There is no organization management, SSO or public SaaS deployment claim.
- The fixed HTTP and MCP catalog can be reconfigured only within administrator-approved contracts. OpenAPI import supports a constrained GET-query / POST-JSON subset and cannot register arbitrary network targets or executable commands.
- All writes target a synthetic local ledger. Effect-plus-receipt atomicity and approval replay do not guarantee exactly-once effects in arbitrary real external services.
- The current demo uses deterministic Fake chat and hash embeddings with PostgreSQL full text/vector RRF. PostgreSQL `simple` tokenization and the small synthetic corpus limit Chinese free-form recall. Multilingual model/embedding quality requires a separate versioned corpus and real-provider study.
- Grounding uses strict deterministic evidence checks. This favors safe refusal and may reject a reasonable paraphrase. Emitted-citation validity must be read alongside E2E, abstention and coverage denominators.
- Context summary is bounded extractive text, not an LLM summary. Fake token accounting uses conservative UTF-8 estimates; real usage comes from provider responses. Unknown prices remain `unknown`; configured cost ceilings cannot assume unknown prices are zero.
- SSE sends validated answer fragments after grounding finishes. It exposes progress before completion but does not stream unvalidated raw model tokens. Reconnect uses durable event replay and cannot invoke a tool.
- The semantic cache stores only retrieval evidence and recognizes a limited safe canonical vocabulary; it is not a general answer cache. It includes permission/version namespaces and revalidates current evidence on every hit.
- Metrics, circuit breakers and rate limits are bounded process-local state. Session, approval, events, checkpoint and audit are durable in PostgreSQL. Restart clears in-process observation history; there is no cluster-wide telemetry warehouse or distributed rate limiter.
- No OCR, image/audio/video ingestion, queues, Kubernetes, workflow canvas, CRM/ERP integration, email, payment, training or multi-Agent swarm is implemented or required by this release.

## Roadmap

1. Versioned retrieval morphology and multilingual embeddings, evaluated on a new dev/test dataset without modifying existing held-out labels.
2. Expand real-provider grounded answer tests and improve supported paraphrase handling while preserving identity, support and coverage checks.
3. Add operator-managed authentication integration, persisted metrics aggregation and documented backups for deployments beyond a single trusted host.

Any future real external write connector needs its own authorization, idempotency and fault-injection contract before it can enter the Registry.
