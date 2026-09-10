# v1.0.0-rc.1 clean acceptance evidence

Tested source: `a8ce87ff063c64d6db5f3e053b2e70411a422d73`. The local release tag points to the following evidence-only commit; the production and test inputs have the same tree contents.

The checkout, native venv, node_modules and project PostgreSQL volume were new. Existing Docker and package download caches were reused. The isolated Web service is bound to loopback port 18090. The full backend container gate ran as UID 1001. No paid key or public model service was used by required Fake gates.

| Gate | Observed result |
| --- | --- |
| Linux PostgreSQL full pytest | 577 passed; 0 failed / errors / skipped; 40.382 s |
| Line coverage | 5230/6083 = 85.98%; minimum 80% |
| Ruff check / format / mypy / diff | Pass; mypy covers 78 source and entry files |
| Vue unit / Chromium E2E | 18 / 4 passed, zero browser retries; E2E 8.608 s |
| Vue install / lint / format / typecheck / build | Pass on locked Node 24.15.0 dependencies, native and container |
| Compose config / build / migrate / seed / readiness | Pass; seed repeated without duplicate Profiles; all runtime services non-root |
| HTTP restart / approval / SSE acceptance | Pass in 22.579 s |
| Two consecutive paced demos | Both pass: 182.141 s, 182.109 s |
| Security | 74 passed; 16 versioned adversarial cases; 0 skips |
| Source/history scan | 280 publishable files, 423 reachable blobs, 0 findings |
| Image scan | 194 application files plus config/build history; 0 findings and no local caches |
| GitHub Actions | Definitions present; local equivalent gates ran. Remote workflows were not triggered. |

## Evaluation and performance

| Metric | Current clean Fake run |
| --- | --- |
| cases | 66 |
| route_accuracy | 1 |
| recall_at_1 | 0.882353 |
| recall_at_3 | 1.000000 |
| recall_at_5 | 1.000000 |
| mrr | 0.941176 |
| citation_validity | 1.000000 |
| claim_support | 1.000000 |
| abstention_accuracy | 0.964286 |
| tool_selection_accuracy | 1 |
| argument_field_f1 | 1.000000 |
| unauthorized_write_rate | 0 |
| kb_isolation_violation_rate | 0 |
| attack_success_rate | 0 |
| e2e_success_rate | 0.984848 |
| error_rate | 0.045455 |
| p50_ms | 141.607097 |
| p95_ms | 329.394227 |
| model_calls | 94 |
| retrieval_calls | 28 |
| tool_calls | 18 |
| input_tokens | 152566 |
| output_tokens | 12939 |
| total_tokens | 165505 |
| cost_microusd | 0 |

Dev: 33/33 E2E; held-out test: 32/33. The remaining `hr-08` morphology miss safely abstains. Error rate includes the three intentional missing-resource cases; it is not a count of unexpected platform crashes. Citation and claim rates cover emitted grounded answers, and must be read alongside abstention/E2E denominators. All three safety rates have independent zero-tolerance gates.

The separate 20-request container benchmark has P50 131.334 ms / P95 156.037 ms, 118.0 mean SQL queries, 40 model calls and 71880 Fake byte tokens, zero errors and zero model cost.

The earlier controlled native baseline → candidate → retest is preserved under `../benchmark-comparison/`: SQL count 148 → 118, candidate P50 246.79 → 216.89 ms. Container timings above are a different environment and are not attributed to that optimization. The EXPLAIN and trace fingerprints establish redundant application roundtrips as the measured bottleneck.

Optional real Provider evidence remains separate in `../real-provider/`: 3 cases, 2/3 E2E, one HR answer rejected by strict Claim support. The optional command exited 1; 6,697 actual tokens, unknown price/cost. This is not a passing real-model quality gate and does not block the required local Fake candidate.

## Reproduce

```sh
python scripts/ops.py bootstrap --project omniagent-clean-check
python scripts/acceptance.py --project omniagent-clean-check --output .pytest-tmp-smoke
python scripts/ops.py test --project omniagent-clean-check
python scripts/ops.py eval --project omniagent-clean-check
python scripts/ops.py benchmark --project omniagent-clean-check
python scripts/acceptance.py --project omniagent-clean-check --output .pytest-tmp-demo-1 --demo-seconds 180
python scripts/acceptance.py --project omniagent-clean-check --output .pytest-tmp-demo-2 --demo-seconds 180
```

Use a new directory and volume. Set `OMNIAGENT_WEB_PORT` and matching acceptance `--base-url` when port 8080 is occupied. `docs/development.md` documents native and image/source security checks. Raw JUnit, coverage XML, diagnostic logs and browser traces stay in ignored local test output or CI artifacts; these public files contain only synthetic data and sanitized aggregate evidence.

The two protected untracked files were not edited or staged. Private learning records were not changed. No push, PR, merge to main or remote Release was performed.
