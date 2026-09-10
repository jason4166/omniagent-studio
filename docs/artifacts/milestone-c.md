# Milestone C verification

Executed on 2026-09-10 with local PostgreSQL, a real HTTP mock process, the MCP stdio server,
the public API, Vite and Chromium. All model responses used the deterministic Fake Provider.

| Gate | Observed result |
| --- | --- |
| Full backend pytest | 496 passed, 0 skipped, 21.95 s |
| Ruff check / format check | Passed / 141 files formatted |
| Strict mypy | Passed, 65 source and entry files |
| git diff --check | Passed |
| Vue lint + Prettier | Passed |
| vue-tsc | Passed |
| Vitest | 16 passed across 3 files |
| Chromium E2E | 4 passed, 19.8 s; no retries |
| Production Vue build | Passed |

Browser E2E covers: HR citation resolution and abstention; read-only HTTP/MCP; sales proposal,
reload recovery, argument editing, approved effect, duplicate approval and offline/online SSE
reconnection without additional POST requests; administrator Profile validation and risk display.
Unit tests cover frame boundaries, foreign events, gaps, duplication, bounded frames, lost POST
responses, repeated approval clicks, argument validation, terminal approval states and HTML escaping.

During validation a raw error dictionary was found in the abstention bubble and replaced by a
readable refusal. Assertions now check business outcomes and persistent usage, not guessed output.
The initial full-library JavaScript bundle was 1,042.52 kB / 340.24 kB gzip. Component imports and
deferred administration reduced the critical bundle to approximately 297 kB / 107 kB gzip; the
administration chunk is approximately 176 kB / 59 kB gzip. This is a build-size comparison, not a
network-latency benchmark.

Reproduction: start `omniagent serve` and `omniagent mock`, then in `apps/web` run `npm ci`,
`npm run dev`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`, and
`npx playwright install chromium && npm run e2e` (run separate commands in PowerShell).
Node 24.15.0 or a newer compatible LTS is required by the locked development toolchain.
The E2E script generates `test-results/hr.png`, `approval.png`, `admin.png`, and JUnit XML.
Backend JUnit is at `.pytest-tmp-all-c/junit.xml`. These raw local artifacts are Git-ignored.
