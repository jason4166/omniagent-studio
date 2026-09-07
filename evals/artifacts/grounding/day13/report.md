# Day 13 Grounding Evaluation

- Dataset: `grounding-v1`
- Dataset SHA-256: `427c985a528239a986de9e1a51e4a28128f0dcc47c84ed38c6710b429168c9d9`
- Cases: 14

## Summary

| Metric | Numerator | Denominator | Rate |
|---|---:|---:|---:|
| Outcome accuracy | 14 | 14 | 1.0000 |
| Decision accuracy | 14 | 14 | 1.0000 |
| Citation validity | 12 | 16 | 0.7500 |
| Claim support | 6 | 12 | 0.5000 |
| Unsupported claims | 6 | 12 | 0.5000 |
| Abstention classification | 14 | 14 | 1.0000 |

Expected abstentions: 7.

## Cases

| Case | Category | Expected | Actual | Failure code | Decision correct |
|---|---|---|---|---|---:|
| grounding-001 | normal | answer | answer | - | yes |
| grounding-002 | normal | answer | answer | - | yes |
| grounding-003 | multi_source | answer | answer | - | yes |
| grounding-004 | multi_source | answer | answer | - | yes |
| grounding-005 | missing_citation | abstain | abstain | missing_citation | yes |
| grounding-006 | wrong_id | abstain | abstain | unknown_citation | yes |
| grounding-007 | unauthorized_id | abstain | abstain | unauthorized_citation | yes |
| grounding-008 | no_answer | abstain | abstain | no_evidence | yes |
| grounding-009 | fabricated_claim | abstain | abstain | unsupported_claim | yes |
| grounding-010 | document_injection | answer | answer | - | yes |
| grounding-011 | overlong_context | abstain | abstain | unknown_citation | yes |
| grounding-012 | conflict | conflict | conflict | - | yes |
| grounding-013 | conflict | abstain | abstain | unanchored_conflict | yes |
| grounding-014 | clarification | clarify | clarify | - | yes |

## Interpretation

Citation validity and Claim support include deliberately invalid drafts. Use decision accuracy to determine whether the validator classified the frozen cases correctly.

## Limitations

- Claim support uses deterministic exact extracts; it does not score semantic paraphrases.
- The frozen suite is synthetic and does not measure a real LLM or embedding provider.
- Citation and claim rates include intentional negative cases and are not validator accuracy.
