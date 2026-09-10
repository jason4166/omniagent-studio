# Local deployment and operations

## Lifecycle

Run from the repository root with Python 3.12, Git and Docker Compose available:

```sh
python scripts/ops.py up
python scripts/ops.py health
python scripts/ops.py seed
python scripts/ops.py down
```

`bootstrap` aliases `up`. Build inputs are allowlisted in `.dockerignore`; the images contain no local Git database, `.env`, uploaded data or private records. Python, Node, uv, PostgreSQL/pgvector and nginx base images are pinned by digest. Google Docker Hub cache and GHCR are used for the same upstream images to avoid a local Docker Hub transport failure. Dependencies are fixed by `uv.lock` and `package-lock.json`; cold builds require registry/package network access.

The default Compose project is `omniagent-v1`, with named volume `omniagent-v1_pgdata`. Only Web is published, at `127.0.0.1:8080`; PostgreSQL, API and mock remain on the Compose network. PostgreSQL, API/mock and nginx use numeric non-root users. Application filesystems are read-only with explicit temporary filesystems. One-off migration and seed services must exit successfully before API readiness.

Use `--project omniagent-clean-<suffix>` for an isolated acceptance deployment. Set `OMNIAGENT_WEB_PORT` before `up` when running a second deployment. `ops.py` embeds the current Git commit in API/mock/test images; container eval rejects a missing or malformed build revision. Rebuild after source changes.

### Reset is destructive

`down` preserves data. `reset` permanently removes only volumes whose exact name and Compose ownership label match the selected project. It refuses without a matching explicit confirmation:

```sh
python scripts/ops.py reset --project omniagent-test-disposable --confirm-reset omniagent-test-disposable
```

This example targets a disposable test project. Do not substitute a project containing data you need. The command prints the exact volume list before deletion. There is no reset in `bootstrap`, tests, migrations or normal `down`.

### Retention and restart

The default session TTL is 24 hours, configurable from 60 seconds to seven days. Expired sessions cannot be read or resumed. Run `python scripts/ops.py purge` for bounded removal of expired session/checkpoint rows and semantic cache entries. Busy sessions are skipped, so maintenance can be repeated. An owner can explicitly delete a conversation even if its Profile is disabled or saved schema invalid. Deletion does not reverse executed effects; hash-only audit and mock idempotency receipts remain.

```sh
docker compose -p omniagent-v1 restart postgres mock api
python scripts/ops.py health
```

Pending approval and completed history survive this restart. Preserve the database volume. There is no automated backup/restore service; a production backup policy is a separate deployment concern.

## Optional real Provider

Fake mode is the default and uses no model key. The optional compatible chat adapter reads these **server-side environment references**, never Profile-embedded secrets:

| Variable | Purpose |
| --- | --- |
| `OMNIAGENT_PROVIDER_API_KEY` | Primary credential provided by the operator |
| `OMNIAGENT_PROVIDER_BASE_URL` | Administrator-selected compatible HTTPS API |
| `OMNIAGENT_PROVIDER_MODEL` | Model for the three-case real baseline command |
| `OMNIAGENT_PROVIDER_THINKING` | Optional `enabled` / `disabled` extension, only for supporting providers |
| `OMNIAGENT_FALLBACK_API_KEY`, `_BASE_URL`, `_MODEL`, `_THINKING` | Optional explicitly configured secondary Provider |

With those variables supplied through the host's secret mechanism, run:

```sh
uv --cache-dir .uv-cache run omniagent eval-real --output .pytest-tmp-real
```

The command uses only three synthetic public policy questions and writes a separate report. It exits nonzero if any case fails, including an answer rejected by strict grounding. Current measured evidence is 2/3, so this optional smoke is not described as passing. Prices are not configured; cost is `unknown`.

For an interactive Profile select `primary` or `primary-with-fallback` and the intended model in the administrator editor, after configuring server environment variables. Fallback occurs only for eligible transient failures, with a bounded total deadline and budgets for every attempt. Authentication, permissions, validation, missing resources and malformed schemas are not retried or hidden by fallback.

The checked-in Compose definition intentionally contains only Fake configuration. To run real models in containers, use an operator-owned Compose override that forwards the named environment references to API and only the required services. Keep that file and credentials outside tracked files and build context. Do not put literal secrets in YAML, Profile JSON, command history or browser storage. Changing the public dev bearer values requires an authentication-capable client or trusted authentication proxy; the bundled identity selector targets local demo identities.

## Observability

Default `OMNIAGENT_TRACE_EXPORTER=none` keeps spans local. The admin API exposes bounded recent spans at `/api/telemetry` and aggregate metrics at `/api/metrics`. `OMNIAGENT_JSON_LOGS=1` enables payload-free structured logs. Restart clears in-memory metrics; persisted audit and event IDs remain in PostgreSQL.

For optional OTLP HTTP export set `OMNIAGENT_TRACE_EXPORTER=otlp`, `OMNIAGENT_OTLP_ENDPOINT` to the operator's HTTPS collector endpoint, and `OMNIAGENT_OTLP_HEADERS_REF` to the name of a server environment variable containing a JSON header object. Langfuse can use this standard OTLP adapter with its documented endpoint and authorization headers. No collector or account is required by Fake tests. Export credentials never enter Profiles or browser responses. Setting exporter back to `none` disables external telemetry.

## Readiness and failure handling

`/health` reports process liveness; `/ready` requires database connectivity and migration readiness. The reverse proxy disables SSE buffering. Server input/upload/response limits, fixed connector timeouts, retries and circuit breakers return typed error codes; the UI keeps validation, unavailable and conflict outcomes visible. Lost write responses can be recovered with the original decision key. A new key does not grant new authorization.

Public loopback dev credentials, process-local rate limiting and a shared PostgreSQL instance are deliberate local-demo boundaries. Do not expose this Compose stack directly as a public multi-user service.
