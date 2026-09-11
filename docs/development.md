# Development and reproducible gates

Required versions are Python 3.12 (tested 3.12.13), uv 0.12.1 and Node 24.15.0 for native frontend development. Exact Python and npm dependencies live in the two lockfiles. Docker users do not need native Node.

## Backend

Use a disposable PostgreSQL 16 / pgvector database. Set both `OMNIAGENT_DATABASE_URL` and `OMNIAGENT_TEST_DATABASE_URL` to its SQLAlchemy psycopg URL. Tests perform writes and cleanup in that database. Do not use a production database. The default Compose database has no host port; `ops.py test` executes on its private network.

```sh
uv --cache-dir .uv-cache sync --locked
uv --cache-dir .uv-cache run omniagent migrate
uv --cache-dir .uv-cache run omniagent seed
uv --cache-dir .uv-cache run pytest --basetemp .pytest-tmp-check -p no:cacheprovider --cov=omniagent --cov-fail-under=80 --cov-report=xml:.pytest-tmp-check/coverage.xml --junitxml=.pytest-tmp-check/junit.xml
uv --cache-dir .uv-cache run ruff check .
uv --cache-dir .uv-cache run ruff format --check .
uv --cache-dir .uv-cache run mypy src/omniagent examples/async_timeout.py examples/routing_eval.py examples/configurable_runtime.py examples/ingestion.py examples/hybrid_retrieval_eval.py examples/grounding_eval.py examples/real_provider_smoke.py examples/bounded_graph.py
git diff --check
```

Markers are `unit`, `contract`, `integration`, `e2e`, `eval`, `security`. Explicit layers remain attached to their tests; legacy isolated tests receive `unit`. Database-backed full gates require both environment variables; absence may skip integration tests and must not be reported as full acceptance. The release and CI gates use a real PostgreSQL service and require zero skips. Fault cases use virtual clocks and condition polling instead of arbitrary test sleeps.

Run `omniagent serve` and `omniagent mock` in separate local processes for native development, with the same database URL and mock port configuration. The v1 API defaults to loopback port 18080 and mock to 18081. Serving requires password authentication and an exact `OMNIAGENT_PUBLIC_ORIGIN`; create an account through the local stdin-only account CLI. Test bearer mode is never accepted by `omniagent serve`. `omniagent mcp-discover` starts the fixed local MCP process and reports tools/resources. No arbitrary subprocess is accepted from users or models.

## Frontend and screenshots

From `apps/web`, with Node 24.15.0:

```sh
npm ci
npm run lint
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run e2e
```

Create an isolated local project with `--test-accounts`. Point `OMNIAGENT_WEB_URL` at its Web URL, and `OMNIAGENT_CREDENTIAL_DIR` at the absolute `.local/deployments/<project>` directory. The browser reads the random member/admin account fixtures from that private directory; no password is embedded in the bundle or committed. E2E uses one worker and zero retries, creates and removes only its own sessions, and writes `test-results/hr.png`, `approval.png`, `admin.png` plus JUnit. Copy reviewed screenshots to `docs/screenshots/` for publication. Do not commit browser traces, local JUnit host metadata or actual user data.

On Windows with an older system Node, the tested isolated alternative is `npm exec --yes --package=node@24.15.0 -- npm run build` (replace `build` with the desired script). It does not require replacing a user's global Node installation.

## Eval, security and performance

Run these serially against the disposable database:

```sh
uv --cache-dir .uv-cache run omniagent eval --output .pytest-tmp-eval --variant candidate
uv --cache-dir .uv-cache run omniagent security --output .pytest-tmp-security
uv --cache-dir .uv-cache run omniagent benchmark --output .pytest-tmp-benchmark --variant candidate
uv --cache-dir .uv-cache run omniagent compare --baseline docs/artifacts/eval-baseline/report.json --candidate docs/artifacts/eval-candidate/report.json --output .pytest-tmp-comparison
uv --cache-dir .uv-cache run python scripts/compare_benchmark.py --help
```

Evaluation freezes dataset, split, Profile, Prompt, model, embedding, retrieval, tool, lockfile and Git identities in JSON. Dev and test metrics remain separate. Unauthorized writes, KB violations and attack success are independent zero-tolerance gates. General route/E2E gates require at least 95%. Citation/support denominators count emitted grounded answers; a high score does not conceal abstentions. The known held-out failure is documented, not removed from the dataset.

The benchmark uses 20 measured identical new-session requests after two warmups, disables semantic cache, records local OTel SQL spans and runs PostgreSQL EXPLAIN. Hardware, process scheduling and shared database load affect latency; compare the same workload hash and preserve both reports. The checked-in baseline/candidate/retest proves query reduction, not a universal production SLA.

`security` runs versioned attacks and scans publishable current files plus every blob reachable from local Git refs. Output contains rule names and fingerprints, never matching secret bytes. Ignored local secrets and private runtime data are outside publication scanning and outside the image build context. Scan history before any proposed remote push.

## Clean acceptance

Create a new clone/directory and a previously nonexistent `omniagent-clean-*` volume. From that clone:

```sh
python scripts/ops.py up --project omniagent-clean-check --port 8082 --test-accounts
python scripts/acceptance.py --project omniagent-clean-check --base-url http://127.0.0.1:8082 --output .pytest-tmp-clean
python scripts/ops.py test --project omniagent-clean-check
python scripts/ops.py eval --project omniagent-clean-check
python scripts/ops.py benchmark --project omniagent-clean-check
uv --cache-dir .uv-cache run python scripts/release_audit.py --project omniagent-clean-check --output .pytest-tmp-image-audit
python scripts/acceptance.py --project omniagent-clean-check --base-url http://127.0.0.1:8082 --output .pytest-tmp-demo-1 --demo-seconds 180
python scripts/acceptance.py --project omniagent-clean-check --base-url http://127.0.0.1:8082 --output .pytest-tmp-demo-2 --demo-seconds 180
```

Set a unique Web port and pass the matching `--base-url` to acceptance when another stack is running. The default fast acceptance has no pacing. `--demo-seconds` deliberately spreads actual demo stages over three to five minutes; it does not turn fixed sleeps into test assertions. Image audit requires a new output directory and checks running image revision, non-root users, configuration/build history and exported public application files.

GitHub Actions workflow files define the same gates. Local execution is the evidence available before an authorized push; a workflow definition alone is not a completed GitHub run.

## Real deployment acceptance

Use a separate project/volume with the two operator credential references configured:

```sh
python scripts/ops.py bootstrap --mode real --project omniagent-clean-live --port 8081 --test-accounts
python scripts/acceptance.py --mode real --project omniagent-clean-live --base-url http://127.0.0.1:8081 --output .pytest-tmp-live
python scripts/ops.py eval-real --mode real --project omniagent-clean-live
uv --cache-dir .uv-cache run python scripts/live_upload_smoke.py --project omniagent-clean-live --base-url http://127.0.0.1:8081 --output .pytest-tmp-upload
uv --cache-dir .uv-cache run python scripts/release_audit.py --mode real --project omniagent-clean-live --output .pytest-tmp-live-image
```

Set a different Web port/base URL when the Fake project is still running. Run the browser
suite against this URL as well; its same five flows use real models and vectors. The
live v3 evaluator (30 business cases and 7 conversation cases) and upload proof invoke paid APIs.
Offline tests must use a separate Fake database. The checked-in real workflow is manual and
requires both provider secrets.

After each user-facing update, the delivery engineer also exercises the deployed real UI with
fresh wording and multi-turn conversations across the three Profiles: informal questions,
follow-ups, topic switches, missing arguments and read-only lookups. Inspect actual replies,
citations, state transitions and approval cards. Open citation sources and edit an approval
through the ordinary field form. Check desktop and
mobile layouts, loading/error states, and that document metadata is escaped and presented only
as a readable source location. Keep model configuration in administration; retain the visible
token/cost summary requested for the conversation workspace.
Use owned test sessions and sandbox tools; remove only those sessions when finished.
Turn discovered failures into focused regressions,
fix them, redeploy and repeat the exploratory conversation before handing off. Users are not
responsible for this acceptance step. Report the observed scope instead of promising that all
possible conversations are error-free.

The repeatable conversation smoke includes social history followed by an HR business question:
`python scripts/conversation_smoke.py --project omniagent-clean-live --base-url http://127.0.0.1:8081 --output .pytest-tmp-conversation`.
It supplements fresh exploratory dialogue and the frozen evaluator; it does not replace either.
