# Local and public operations

Use `python scripts/ops.py bootstrap --mode real` for the real chat/vector portfolio,
or `--mode fake` for a key-free offline deployment. Defaults are distinct projects
`omniagent-secure-real` / `omniagent-secure-fake`, each with its own PostgreSQL volume.
Both require password login. Bootstrap prints the private initial account file path;
it never prints passwords, and repeating it never resets an existing account.

The default Web origin is `http://127.0.0.1:8080`. Set `OMNIAGENT_WEB_PORT` before
bootstrap for another local port and use that exact origin in the browser. Do not
mix localhost and 127.0.0.1. API, PostgreSQL and mock ports remain internal. For an
actual domain, use [public deployment](public-deployment.md) with the production
HTTPS overlay. Merely binding the local configuration to another interface is not
supported public deployment.

```sh
python scripts/ops.py bootstrap --mode real
python scripts/ops.py health --mode real
python scripts/ops.py seed --mode real
python scripts/ops.py purge --mode real
python scripts/ops.py down --mode real
python scripts/ops.py up --mode real
```

`down` preserves volumes. A service restart preserves accounts, sessions,
checkpoints, pending approvals and idempotency receipts. `purge` removes expired
session/checkpoint data and expired login/quota/stream records. Production mode is
pinned to its origin and refuses offline test/eval/reset operations.

## Disposable test deployment

Use a separate Fake project and database. Test accounts are random, private
fixtures enabled only by `--test-accounts` on a local test/clean/CI project.

```sh
python scripts/ops.py bootstrap --project omniagent-test-check --test-accounts
python scripts/ops.py test --project omniagent-test-check
python scripts/ops.py eval --project omniagent-test-check
python scripts/ops.py benchmark --project omniagent-test-check
```

These gates do create/delete synthetic rows and must never target a user database.
The test container gets the owner credential separately; the serving API keeps
its restricted runtime credential. Reports are in `.pytest-tmp-container-reports/`.
Real evaluation requires a separate local real project and explicit `eval-real`.

**Destructive reset is a separate command.** The following deletes only the named
project's owned Docker volumes after verifying their Compose labels. Never use it
for data to retain. A production deployment refuses this command even if confirmed.

```sh
python scripts/ops.py reset --project omniagent-test-check --confirm-reset omniagent-test-check
```

Reset does not rotate or delete private bootstrap credentials. Do not manually
remove `.local` while its database volume is still needed. Back up the database
and retain the related deployment secret files under the operator's access policy.

## Real providers and secret references

First real bootstrap requires host process credentials `DEEPSEEK_API_KEY` and
`ZHIPUAI_API_KEY`. It creates private read-only mounted files once. Subsequent runs
read those files; environment changes do not silently rotate existing secrets.
Rotate a file deliberately with restricted permissions and restart the affected
services. Values never enter Compose config, images, Profiles or the browser.

Chat requests `deepseek-v4-flash` with thinking disabled; real embedding is Zhipu
`embedding-3`, 1024 dimensions. `OMNIAGENT_REAL_MODEL` selects a compatible alternative
before creating/seeding a new deployment. Index identity includes provider/model,
dimension and endpoint version. Do not reuse Fake vectors or an incompatible real
index. Business effects remain inside the local synthetic mock service.

Native deployment supports `OMNIAGENT_PROVIDER_API_KEY_FILE`, `_BASE_URL`, `_MODEL`
and optional `_THINKING`. For vectors set `OMNIAGENT_EMBEDDING_PROVIDER=primary`,
`OMNIAGENT_EMBEDDING_MODEL`, `_BASE_URL`, `_API_KEY_FILE`. `OMNIAGENT_DATABASE_URL_FILE`
resolves the database credential. Do not set both a value and its file reference.

Optional controlled fallback uses `OMNIAGENT_FALLBACK_API_KEY_FILE`, `_BASE_URL`,
`_MODEL` and optional `_THINKING`, then an explicitly selected
`primary-with-fallback` Profile. Only transient failures qualify. Every model
attempt still consumes persisted budgets and public quotas. Authentication,
permission, validation, missing resources and bad schemas never retry/fall back.
The release does not claim a second paid model was live-tested.

## Observability and recovery

`OMNIAGENT_TRACE_EXPORTER=none` keeps spans local; admin `/api/telemetry` and
`/api/metrics` show bounded observations. `OMNIAGENT_JSON_LOGS=1` enables payload-free
structured logs. Request/trace/run/thread IDs correlate operations without exposing
prompts, passwords or hidden reasoning. Metrics/circuit state is process-local;
audits, quotas and workflow records survive restart in PostgreSQL.

Optional OTLP HTTP export uses `OMNIAGENT_TRACE_EXPORTER=otlp`, an operator HTTPS
`OMNIAGENT_OTLP_ENDPOINT` and `OMNIAGENT_OTLP_HEADERS_REF` pointing to a server variable
containing the JSON headers. This adapter can use Langfuse's documented OTLP endpoint.
No telemetry account is required, and the release makes no external collector SLA claim.

`/health` is liveness; `/ready` verifies the migrated database and rejects a privileged
production API role. Nginx disables SSE buffering and uses Docker DNS after restarts.
Caddy adds TLS and HSTS in production. Health and readiness disclose no credentials.

Encrypted backup, new-database restore, off-host key handling, account recovery and
remaining target-server acceptance are documented in [public deployment](public-deployment.md).
The backup and PDF helpers are bounded single-server implementations, not a claim
of unlimited document size, continuous availability or organization-scale operations.
