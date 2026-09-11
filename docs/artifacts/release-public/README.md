# rc.3 public-access hardening evidence

Validated runtime/test commit: `f82b6053d63410056d2cb4a2c71cf83d2b07a75b`.
The subsequent documentation commit archives these reports and screenshots; it does
not change the runtime. The local `v1.0.0-rc.3` tag identifies the complete candidate.
Earlier `release/` and `release-real/` folders remain historical rc.1/rc.2 evidence.

- [Generated metrics](metrics.md), [gate summary](gates.json), [runtime identity](runtime-identity.json).
- [Real candidate](real-candidate/report.md), [real baseline](real-baseline/report.md),
  [comparison](real-comparison/comparison.md), [Fake evaluation](fake-eval/report.md).
- [Security gate](security/security.md), [dependency audit](dependencies.json),
  [source/history scan](security/secret-scan.json).
- [Clean reproduction](reproduction.json), [Fake acceptance](acceptance-fake.json),
  [real acceptance](acceptance-real.json), [real new-upload proof](upload-proof.json).
- [Verified local TLS/access](tls-access.json), [production edge audit](edge-audit.json),
  [encrypted recovery](recovery.json), [real image scan](image-audit-real.json),
  [Fake image scan](image-audit-fake.json).
- [Demo 1](demo-1.json), [demo 2](demo-2.json), [current local user deployment](user-deployment.json).
- [Runtime benchmark](benchmark/benchmark.md), and the earlier same-workload
  [SQL optimization experiment](../benchmark-comparison/comparison.md).

The release is real chat + real vectors with sandboxed business effects. Fake is
the independent required CI baseline. Live requests use `deepseek-v4-flash` and
report the provider's `deepseek-flash` alias; Zhipu vectors use `embedding-3`, 1024
dimensions. Prices are unconfigured and stay `unknown`. Synthetic licensed data
does not establish general domain accuracy, customer traffic or an SLA.

The real baseline and candidate each pass 24/24. Their only intervening source
change fixes a test fixture's assumption about an empty account database. Runtime
files are identical; latency differences are observation noise, not an optimization
claim. Real error_rate includes one deliberately nonexistent product (expected
404), counted as successful error handling by E2E. Fake retains the frozen held-out
safe abstention (65/66); labels were not rewritten.

The benchmark and evaluators use explicit test-only authentication to compare
the runtime. Public authentication has separate cookie, CSRF, authorization,
quota, browser and TLS gates. HTTPS was actually verified against a local trusted
CA, with certificate verification enabled. No public domain/DNS/ACME certificate
issuance or external server deployment is asserted. The recovery drill retained
one pending approval and four checkpoints in a new database, revoked restored
logins, and rejected tampering before any database was created. Promotion of the
restore database to live traffic remains an operator action.

The clean checkout uses new named volumes, freshly installed npm dependencies,
Linux tests and actual HTTP/browser requests. A first Linux test run failed because
the bootstrap administrator invalidated a sole-admin fixture assumption. The fixed
test uses a rollback-only arrangement; the final Linux and Windows suites both pass
618 tests with zero skips. No allow-failure or retry was used to hide that result.

The API/mock exports match the 143 sealed runtime/configuration source files where
applicable; 210 exported source/preset/migration files were checked in each of the
real and Fake deployments. Application images exclude development caches, private
accounts and credentials. Source/history scanning covers publishable files and
every Git-reachable blob; ignored local secret stores are outside publication and
the Docker build allowlist. Pattern/advisory scans cannot prove that no unknown
vulnerability or unrecognized secret format exists.

Raw JUnit/coverage artifacts remain in ignored local output directories and are
produced by CI. Public summaries omit host metadata, credentials, browser traces
and raw account files. `manifest.json` records hashes of the public evidence. The
GitHub workflow definitions were exercised locally; hosted GitHub runs were not
triggered because no remote publication was authorized.
