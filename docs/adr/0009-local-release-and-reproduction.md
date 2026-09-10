# ADR 0009: Reproducible local release, isolated volumes and evidence

Status: accepted for v1.0.0-rc.1.

The release is a local demonstration candidate, built from a Git revision with frozen Python/npm dependencies and digest-pinned base images. Python metadata uses the PEP 440 spelling `1.0.0rc1`; Web, API and local Git release naming use the equivalent `1.0.0-rc.1`. A local annotated tag identifies an evidence commit; report files separately identify the immutable source commit tested before that evidence-only commit.

Docker Compose is the delivery boundary. API, Web, mock, PostgreSQL/pgvector, migration and seed are explicit services. Only the Web port is published, on loopback. Services are non-root; API/Web/mock use read-only application filesystems and explicit temporary storage. Persistent state is in one project-labelled PostgreSQL volume. Ordinary up/down never removes it. Reset requires exact project confirmation and verified volume ownership before removal.

The original development Compose project is not reused. Acceptance runs in a fresh clone and a previously nonexistent `omniagent-clean-*` volume, then tests actual restart, approval response loss/replay and SSE reconnection. Test containers use their own report bind directory; Linux report ownership matches the invoking non-root operator. Tests should not run concurrently with eval/benchmark against the same database.

Default Fake mode has no secret or real external business dependency. The build context allows only public source, configuration and synthetic fixtures. Image audit checks actual running image configuration, build history and exported application assets; source scan checks publishable files and all reachable Git blobs. Ignored private data is excluded from the release boundary.

The local network failed to serve Docker Hub requests and Debian HTTP package indexes reliably. The selected artifacts remain pinned upstream images from Google cache/GHCR and the official Debian source over HTTPS. Lockfiles, not a mirror's moving tag, determine Python/npm dependency resolution. CI actions are also pinned by commit.

Required CI uses Fake Provider and PostgreSQL service containers. Real-provider smoke is an explicit manual workflow and fails visibly on any unsuccessful case; it is not a hidden dependency or allow-failure default gate. JUnit, coverage, eval, security and browser outputs are artifacts. Public reports omit hostnames, raw trace payloads and credentials. A local successful run does not imply an unexecuted GitHub Actions run succeeded.

No remote push, PR, merge or remote Release is part of this decision. The user controls remote publication.

The paced restart test exposed stale upstream DNS after the API's container address changed. Nginx now resolves the fixed `api:8000` origin through Docker's internal resolver with a five-second validity and two-second resolver timeout. URI and authorization remain unchanged; no user-controlled hostname enters proxy configuration. Web health uses `/ready` so a live proxy with an unreachable API is not reported healthy. See the official [proxy_pass variable resolution](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass) and [resolver](https://nginx.org/en/docs/http/ngx_http_core_module.html#resolver) contracts.
