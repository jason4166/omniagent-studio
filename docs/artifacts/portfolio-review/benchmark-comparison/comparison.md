# Benchmark observations

Comparison: repeatability

| Metric | Baseline | Candidate | Retest | Change % |
| --- | ---: | ---: | ---: | ---: |
| p50_ms | 267.6051895005003 | 194.98500849977063 | 162.5852004999615 | -27.13706006086025 |
| p95_ms | 366.8070680003894 | 253.8028854004097 | 223.82421415004504 | -30.80752593345877 |
| mean_database_queries | 131 | 131 | 131 | 0.0 |
| mean_database_ms | 62.04399435 | 40.5535222 | 34.8891781 | -34.637473578456024 |

Recorded controls do not freeze host load. The report makes no automatic optimization-retention decision; inspect traces, EXPLAIN and repeated results.
