# Day 12 Retrieval Evaluation: candidate

- Dataset: `retrieval-v1`
- Dataset SHA-256: `4853b54ec1468b179621fd0826017f8bf227aebbc65c3a2688e849d70da67f49`
- Corpus SHA-256: `8f77ac57d9ec1e957940eff04b528557f3528439d9992e615703adc46e86568e`
- Embedding: `fake-sha256-v1` (8 dimensions)
- Chunks: 11
- Config: `top_k=5`, `candidate_k=20`, `rank_constant=60`, `text_query_operator=or`

## Summary

| Mode | Recall@1 | Recall@3 | Recall@5 | MRR | No-answer empty rate |
|---|---:|---:|---:|---:|---:|
| vector | 0.1538 | 0.5000 | 0.8846 | 0.3885 | 0.0000 |
| text | 0.6923 | 0.8462 | 0.8462 | 0.7692 | 0.5000 |
| hybrid | 0.4615 | 0.9615 | 0.9615 | 0.7051 | 0.0000 |

## Lowest-scoring cases

### vector

| Case | Category | Recall@5 | RR | Returned |
|---|---|---:|---:|---:|
| retrieval-012 | no_answer | n/a | n/a | 5 |
| retrieval-013 | no_answer | n/a | n/a | 4 |
| retrieval-014 | cross_kb | 0.0000 | 0.0000 | 5 |

### text

| Case | Category | Recall@5 | RR | Returned |
|---|---|---:|---:|---:|
| retrieval-010 | long_chinese | 0.0000 | 0.0000 | 0 |
| retrieval-011 | long_chinese | 0.0000 | 0.0000 | 0 |
| retrieval-012 | no_answer | n/a | n/a | 5 |

### hybrid

| Case | Category | Recall@5 | RR | Returned |
|---|---|---:|---:|---:|
| retrieval-012 | no_answer | n/a | n/a | 5 |
| retrieval-013 | no_answer | n/a | n/a | 4 |
| retrieval-010 | long_chinese | 0.5000 | 0.5000 | 5 |

## Limitations

- Vector scores use deterministic FakeEmbedding and do not demonstrate semantic quality.
- PostgreSQL simple text search does not provide professional Chinese word segmentation.
- No-answer evaluation measures empty retrieval only; no confidence threshold is configured.
