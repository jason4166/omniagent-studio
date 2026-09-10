# Frozen evaluation comparison

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| route_accuracy | 0.9848484848484849 | 1 | 0.015151515151515138 |
| recall_at_1 | 0.8823529411764706 | 0.8823529411764706 | 0.0 |
| mrr | 0.9117647058823529 | 0.9411764705882353 | 0.02941176470588236 |
| citation_validity | 1.0 | 1.0 | 0.0 |
| claim_support | 1.0 | 1.0 | 0.0 |
| e2e_success_rate | 0.9696969696969697 | 0.9848484848484849 | 0.015151515151515138 |
| p50_ms | 258.1939000010607 | 225.692349999008 | -32.50155000205268 |
| p95_ms | 519.661874999656 | 462.4102500038134 | -57.251624995842576 |
| model_calls | 93 | 94 | 1.0 |
| retrieval_calls | 27 | 28 | 1.0 |
| tool_calls | 18 | 18 | 0.0 |
| total_tokens | 161734 | 165505 | 3771.0 |

Candidate gate: **True**. Safety gates: `{'unauthorized_write_zero': True, 'kb_isolation_zero': True, 'attack_success_zero': True}`.

Latency is measured on local Fake runs; the benchmark report separately measures repeated workloads. No real-model comparison is implied.
