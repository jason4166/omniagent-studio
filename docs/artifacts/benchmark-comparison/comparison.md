# Measured database round-trip reduction

| Metric | Baseline | Candidate | Re-test | Candidate change |
| --- | ---: | ---: | ---: | ---: |
| p50_ms | 246.7945 | 216.8930 | 214.1710 | -12.12% |
| p95_ms | 279.3522 | 273.7405 | 238.2925 | -2.01% |
| mean_database_queries | 148.0000 | 118.0000 | 118.0000 | -20.27% |
| mean_database_ms | 91.3191 | 76.5452 | 75.0967 | -16.18% |

Optimization retained: **True**. See ADR 0008 and the source JSON EXPLAIN plans.

Three Profile/Tool/KB query fingerprints decreased from 28 to 18 occurrences per request. Each request still checks current permissions at every graph boundary. The small-table sequential scan was not the bottleneck; redundant application round trips were. P95 has visible local scheduling noise. Real-provider latency is a separate dataset.
