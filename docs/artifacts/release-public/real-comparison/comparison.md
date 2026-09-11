# Frozen evaluation comparison

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| route_accuracy | 1 | 1 | 0.0 |
| recall_at_1 | 1.0 | 1.0 | 0.0 |
| mrr | 1.0 | 1.0 | 0.0 |
| citation_validity | 1.0 | 1.0 | 0.0 |
| claim_support | 1.0 | 1.0 | 0.0 |
| e2e_success_rate | 1 | 1 | 0.0 |
| p50_ms | 1463.6138370005938 | 1724.320984998485 | 260.7071479978913 |
| p95_ms | 2390.286987303261 | 2534.756662899599 | 144.46967559633822 |
| model_calls | 35 | 35 | 0.0 |
| retrieval_calls | 11 | 11 | 0.0 |
| tool_calls | 8 | 8 | 0.0 |
| total_tokens | 36558 | 36600 | 42.0 |

Candidate gate: **True**. Safety gates: `{'unauthorized_write_zero': True, 'kb_isolation_zero': True, 'attack_success_zero': True}`.

Provider mode: real. Latency includes the measured API workflow; the benchmark report separately measures repeated workloads. Vendor model aliases and network load may change between live runs.
