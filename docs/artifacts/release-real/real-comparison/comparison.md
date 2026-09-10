# Frozen evaluation comparison

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| route_accuracy | 1 | 1 | 0.0 |
| recall_at_1 | 1.0 | 1.0 | 0.0 |
| mrr | 1.0 | 1.0 | 0.0 |
| citation_validity | 1.0 | 1.0 | 0.0 |
| claim_support | 1.0 | 1.0 | 0.0 |
| e2e_success_rate | 1 | 1 | 0.0 |
| p50_ms | 1692.7336000007926 | 1377.4697850003577 | -315.263815000435 |
| p95_ms | 2416.8040149990698 | 2305.389082148758 | -111.41493285031174 |
| model_calls | 35 | 35 | 0.0 |
| retrieval_calls | 11 | 11 | 0.0 |
| tool_calls | 8 | 8 | 0.0 |
| total_tokens | 34513 | 36617 | 2104.0 |

Candidate gate: **True**. Safety gates: `{'unauthorized_write_zero': True, 'kb_isolation_zero': True, 'attack_success_zero': True}`.

Provider mode: real. Latency includes the measured API workflow; the benchmark report separately measures repeated workloads. Vendor model aliases and network load may change between live runs.
