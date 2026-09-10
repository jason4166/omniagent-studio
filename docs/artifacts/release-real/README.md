# v1.0.0-rc.2 — real inference release evidence

Runtime source: `8156cb89cdbbe5b8b19cc63ab20877b9512c1f85`. The release candidate adds public documentation and evidence
around this tested source. [Runtime identity](runtime-identity.json) hashes all 136 tracked
runtime/build/operator files and checks actual exported API/mock source against Git.
The final artifact manifest records canonical LF bytes for text and original screenshot bytes.

This replaces rc.1 as the résumé demonstration. Historical rc.1 reports remain unchanged
under `../release/` and `../real-provider/`; the earlier three-case chat-only smoke used
Fake vectors and is not evidence for this live embedding deployment.

| Gate | Actual result |
| --- | --- |
| Clean Linux backend | 589 passed, 0 skipped/failures/errors |
| Coverage | 5418/6200 = 87.39% (80% gate) |
| Ruff / format / mypy / diff | Passed; mypy includes 81 files |
| Fresh npm ci + frontend | Lint/typecheck/build passed; 18 unit tests passed |
| Chromium | Real 4/4 and Fake 4/4, zero retries |
| Safety / fault injection | 74 security tests passed; 16 versioned attacks; 14 fault scenarios in full suite |
| Real baseline / candidate / retest | 24/24 in each run; dev/test 12 each, same frozen corpus |
| Candidate safety | Unauthorized write, foreign KB and attack success all zero, independent gates |
| Source/history and images | Zero findings; real image audit examines 200 application files |
| Clean deployment | Fresh clone, separate previously nonexistent real and Fake volumes; build/up/migrate/seed/health and restart acceptance passed |
| Real paced demos | 182.17 and 182.14 seconds, both complete and passing |

## Reports and evidence boundaries

- [All gate counters](gates.json), [real acceptance](acceptance-real.json), [Fake acceptance](acceptance-fake.json).
- [Live baseline](real-baseline/report.md), [candidate](real-candidate/report.md), [retest](real-retest/report.md), [comparison and chart](real-comparison/comparison.md).
- [New document + new Profile proof](upload-proof.json), [demo 1](demo-1.json), [demo 2](demo-2.json).
- [Offline evaluation](fake-eval/report.md), [current benchmark + EXPLAIN](benchmark/benchmark.md), [security](security/security.md), [real image audit](image-audit-real.json).
- [Preserved failed multi-turn attempt](failed-multiturn-acceptance.json): a clear question was safely clarified instead of retrieved/refused. The shared routing instructions were corrected using this dev workflow; frozen test labels were not edited.

The native Windows live baseline predates the routing clarification. Candidate and retest
use Linux Compose with the same requested model, real embedding index and dataset. Their
latencies are observations, not a controlled cross-platform speedup claim. The independent
historical SQL experiment under `../benchmark-comparison/` is the controlled optimization
record. Current SQL count is 119 including an added embedding-version guard.

Candidate chat usage is 34,764 input + 1,853 output = 36,617
tokens over 35 model calls. Query embeddings report 154 tokens over
11 calls; ingestion calls are outside this evaluation window. Chat and
embedding prices remain unknown. The one error outcome is the expected missing-product
404, not an ignored infrastructure failure. Live aliases can change; Git cannot freeze
vendor weights. One corpus repeated three times is not 72 independent examples.

The mandatory Fake suite remains 65/66, with a documented safe held-out lexical abstention.
Fake byte-based token estimates and $0 fixture costs are never presented as paid-model usage.
All business effects are synthetic local ledger writes. No real CRM, email, payment,
enterprise SSO, public multi-tenant deployment, remote push or hosted CI run is claimed.
