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

The default Compose project is `omniagent-v1`, with named volume `omniagent-v1_pgdata`. Only Web is published, at `127.0.0.1:8080`; PostgreSQL, API and mock remain on the Compose network. PostgreSQL, API/mock and nginx use numeric non-root users. Fake application filesystems are read-only. Real API/seed permit Docker Compose to provision environment-backed secrets; their code and dependencies are root-owned and cannot be changed by the non-root runtime user. Temporary storage uses tmpfs. One-off migration and seed services must exit successfully before API readiness.

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

## Real chat and real embeddings

For the résumé demonstration, select the checked-in real overlay:

```sh
python scripts/ops.py bootstrap --mode real
python scripts/ops.py health --mode real
python scripts/ops.py seed --mode real
python scripts/ops.py eval-real --mode real
python scripts/ops.py down --mode real
```

Before boot, supply `DEEPSEEK_API_KEY` and `ZHIPUAI_API_KEY` through the host environment
or a local secret manager. Do not type a literal credential into source, YAML or shell
history. `compose.real.yaml` refers to their names; Docker mounts the values as secret
files only into services that need them. API/seed log no credential values. Resolved
Compose configuration contains names and references, not the credentials. The public
mock service and browser receive neither key.

Real mode uses the isolated project `omniagent-real` and volume `omniagent-real_pgdata`.
The requested chat model is `deepseek-v4-flash`, with thinking disabled, at DeepSeek's
HTTPS API. Live responses currently report the alias `deepseek-flash`; this does not
freeze cloud weights. Vectors use Zhipu `embedding-3`, 1024 dimensions, for both uploads
and queries. There is no Fake fallback. A new installation creates three `primary`
Profiles without the offline routing fixtures. Repeated seed does not replace operator
edits. A different chat model can be explicitly configured in the Profile editor;
`OMNIAGENT_REAL_MODEL` changes the initial seed model only.

Do not point real seed at the old Fake volume. An incompatible Profile or embedding
index raises a conflict. Changing embedding model/endpoint requires a new index/KB and
an explicit Profile change; no existing knowledge is silently erased. Use `--project
omniagent-clean-<suffix>` and a different `OMNIAGENT_WEB_PORT` for another isolated run.

The live evaluator runs 24 frozen Chinese cases, independently from the 66-case required
Fake suite. It writes `.pytest-tmp-container-reports/real-candidate/report.json` and `.md`,
records real chat and embedding usage separately, and fails on mismatched outcomes or
safety gates. It invokes paid APIs; absent or invalid keys produce an error. Prices are
not pinned, so cost remains `unknown`. Run offline tests/eval/benchmark using `--mode fake`
and a separate test project. The operator CLI refuses offline gates in real mode.

Native deployment references are `OMNIAGENT_PROVIDER_API_KEY_FILE` (or `_API_KEY`),
`OMNIAGENT_PROVIDER_BASE_URL`, `OMNIAGENT_PROVIDER_MODEL`, and optionally
`OMNIAGENT_PROVIDER_THINKING`. For embeddings set `OMNIAGENT_EMBEDDING_PROVIDER=primary`,
`OMNIAGENT_EMBEDDING_MODEL`, `_BASE_URL`, and `_API_KEY_FILE` (or `_API_KEY`). Do not set both
a value and file reference for one credential. Profiles never store either value.

For controlled real fallback, configure `OMNIAGENT_FALLBACK_API_KEY_FILE`, `_BASE_URL`,
`_MODEL` and optional `_THINKING`, then explicitly select `primary-with-fallback` in a
Profile. Only transient failures qualify; the total deadline and every model attempt's
budget still apply. Authentication, permissions, validation, missing resources and bad
schemas do not retry or fall back. Demo identities are local RBAC fixtures, not SSO.

## Observability

Default `OMNIAGENT_TRACE_EXPORTER=none` keeps spans local. The admin API exposes bounded recent spans at `/api/telemetry` and aggregate metrics at `/api/metrics`. `OMNIAGENT_JSON_LOGS=1` enables payload-free structured logs. Restart clears in-memory metrics; persisted audit and event IDs remain in PostgreSQL.

For optional OTLP HTTP export set `OMNIAGENT_TRACE_EXPORTER=otlp`, `OMNIAGENT_OTLP_ENDPOINT` to the operator's HTTPS collector endpoint, and `OMNIAGENT_OTLP_HEADERS_REF` to the name of a server environment variable containing a JSON header object. Langfuse can use this standard OTLP adapter with its documented endpoint and authorization headers. No collector or account is required by Fake tests. Export credentials never enter Profiles or browser responses. Setting exporter back to `none` disables external telemetry.

## Readiness and failure handling

`/health` reports process liveness; `/ready` requires database connectivity and migration readiness. The reverse proxy disables SSE buffering. Server input/upload/response limits, fixed connector timeouts, retries and circuit breakers return typed error codes; the UI keeps validation, unavailable and conflict outcomes visible. Lost write responses can be recovered with the original decision key. A new key does not grant new authorization.

Public loopback dev credentials, process-local rate limiting and a shared PostgreSQL instance are deliberate local-demo boundaries. Do not expose this Compose stack directly as a public multi-user service.
