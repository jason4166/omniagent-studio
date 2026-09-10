# Milestone D verified evidence

Baseline source commit: `5da5e7cce7fcb0a7920e6e90c66d475a0ee28fb5`.
Candidate source commit: `d02480ee031f5cbf834ecb8743d8158447bec180`.
Reports lock code hashes, the Git commit, dependency lockfile, Profile, Prompt, KB/source, tools, model, embedding and retriever versions. Private traces and machine-specific JUnit files are excluded from Git.

| Gate | Observed result |
| --- | --- |
| Full pytest with PostgreSQL and coverage | 563 passed, 0 skipped; 44.81 s |
| Line coverage | 5,188 / 6,073 = 85.4273011691092% |
| Ruff / format / mypy / diff | passed; 175 formatted Python files; 78 typed source/entry files at source gate |
| Vue lint / typecheck / build / unit | passed; 16 unit tests |
| Browser HR / HTTP / MCP / approvals / SSE / admin | 4 passed, 21.3 s; no retries |
| Dedicated security command | 69 passed, 0 skipped; 10.34 s |
| Secret/history scan | 253 publishable files, 359 reachable blobs, 0 findings at this scan |
| Fault manifest | 14 named scenarios covering LLM, embedding, database, HTTP, MCP, checkpoints and SSE |

The browser run verifies the D UI and event contracts; the subsequent Profile-read optimization and embedding deadline change additionally passed the full backend gates. Final clean-container browser acceptance is part of milestone E.

Frozen Fake evaluation, 66 cases (33 dev / 33 test, 22 per Profile, 23 attacks):

| Metric | Candidate |
| --- | ---: |
| Route accuracy | 1.0 |
| Recall@1 / @3 / @5 | 0.8823529412 / 1.0 / 1.0 |
| MRR | 0.9411764706 |
| Citation validity / exact claim support | 1.0 / 1.0 (16 emitted items each) |
| Abstention accuracy | 0.9642857143 |
| Tool selection / argument field F1 | 1.0 / 1.0 |
| Unauthorized write / KB isolation / attack success | 0 / 0 / 0; independent gates pass |
| E2E | 65/66 = 0.9848484848; dev 33/33, test 32/33 |
| P50 / P95 | 225.69235 / 462.41025 ms |
| Error rate | 3/66, including intentional missing-record tool failures |
| Model / retrieval / tool calls | 94 / 28 / 18 |
| Input / output / total Fake byte tokens | 152,566 / 12,939 / 165,505 |
| External model cost | 0 |

`hr-08` remains a held-out lexical failure: “hotel nightly limit” does not match the Fake provider's “Hotels” excerpt selection. It safely abstains. The development failure `sales-03` was fixed by prioritizing policy-question intent. Labels and held-out examples were not edited. See `eval-comparison/comparison.svg`.

The 20-request benchmark used two warmups and disabled the semantic cache. Baseline/candidate/re-test P50: 246.7945 / 216.89295 / 214.171 ms. P95: 279.352235 / 273.740475 / 238.292535 ms. Database statements per request: 148 / 118 / 118. Candidate query count fell 20.27%, P50 12.12%, P95 2.01%; local P95 noise is visible in the re-test. The trace and EXPLAIN evidence supports retaining the change; see ADR 0008 and generated benchmark comparison.

The separate real-provider run on the candidate commit used three synthetic policy queries, explicit non-thinking mode, configured `deepseek-v4-flash` and seeded Fake embeddings. Route accuracy was 3/3; E2E was 2/3. The HR draft failed exact claim support and was rejected with `unsupported_claim`; the two emitted answers passed citation and exact claim checks. Six model calls used 5,977 input and 720 output tokens (6,697 total), P50 2,346.132 ms / P95 3,020.1564 ms, cost **unknown**. This optional smoke exits nonzero for the failed case and is not a required Fake CI dependency. Provider aliases are not an immutable model-weights guarantee.
