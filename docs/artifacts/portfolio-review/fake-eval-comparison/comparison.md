# Frozen evaluation comparison

Comparison kind: **repeatability**. Missing identity: []; changed identity: [].
Deltas are omitted when recorded controls are missing or different. Matching controls alone does not establish an optimization.

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| route_accuracy | 1 | 1 | 0.0 |
| recall_at_1 | 0.9130434782608695 | 0.9130434782608695 | 0.0 |
| mrr | 0.9565217391304348 | 0.9565217391304348 | 0.0 |
| citation_validity | 1.0 | 1.0 | 0.0 |
| claim_support | 1.0 | 1.0 | 0.0 |
| e2e_success_rate | 0.9861111111111112 | 0.9861111111111112 | 0.0 |
| p50_ms | 170.3338015004192 | 193.0685879997327 | 22.734786499313486 |
| p95_ms | 331.83278174983576 | 685.2635089496745 | 353.4307271998387 |
| model_calls | 106 | 106 | 0.0 |
| retrieval_calls | 34 | 34 | 0.0 |
| tool_calls | 18 | 18 | 0.0 |
| total_tokens | 390144 | 390144 | 0.0 |

Candidate gate: **True**. Safety gates: `{'unauthorized_write_zero': True, 'kb_isolation_zero': True, 'attack_success_zero': True}`.

Provider mode: fake. Latency includes the measured API workflow; the benchmark report separately measures repeated workloads. Vendor model aliases and network load may change between live runs.
