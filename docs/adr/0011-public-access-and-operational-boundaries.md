# ADR 0011: Independent accounts and a fail-closed public entry

Status: accepted, 2026-09-11. Supersedes the local demonstration authentication
boundary in ADR 0006/0009. Existing rc.1/rc.2 evidence is historical.

## Problem

The local demo embedded role tokens in its browser bundle and mapped each role to
one user. Loopback binding limited exposure, but those identities were unsuitable
for publishing a multi-user portfolio site. Replacing the token strings would not
create independent users. Default database credentials and process-local quotas
also could not serve as a public deployment boundary.

## Decision

- Use invite-only, administrator-created accounts with random UUID identities,
  Argon2id password hashes and independently assigned roles/Profile grants. No
  public registration or browser-selectable role. The first account and database
  passwords are random per installation; repeated bootstrap never resets them.
- Store only SHA-256 hashes of 256-bit opaque session tokens in PostgreSQL. Use
  HttpOnly, SameSite=Strict cookies, Secure and `__Host-` in HTTPS mode. Require an
  exact canonical Host/Origin and a session-bound CSRF token for mutations.
  Password/account changes revoke old logins; SSE rechecks authorization while
  streaming. The final active administrator cannot be removed.
- Restrict historical bearer fixtures to explicit test mode. Reject that mode in
  the serving CLI and fail the old API entry point closed outside tests.
- Reserve request, login, account, session, upload, embedding and model allowances
  atomically in PostgreSQL before work. Retries consume allowance too. Reserve
  conservative token bounds rather than charging unknown prices as zero.
- Run migrations with an owner credential. Run the API with a separate CRUD role
  and the mock with only its approval/effect permissions. Mount individual secret
  files read-only; retain immutable API files and an unprivileged container user.
- Add an explicit production Compose overlay with Caddy TLS, health checks,
  constrained memory/processes, private internal services and durable certificate
  volumes. Pin deployment mode/origin to prevent accidental downgrade by a later
  command. Production targets reject test/eval/reset operations.
- Parse PDF in a fixed subprocess with bounded pages, text, output, wall time and
  Linux memory/CPU limits. Do not place providers or secrets in its environment.
- Provide authenticated AES-GCM backups. Authenticate before creating the restore
  database, restore only into a new database, and revoke restored login sessions.

## Consequences and evidence

The target is a single-server, limited-audience project with managed accounts.
SSO, multi-organization tenancy, MFA, public registration and an external identity
provider are outside this release. A host/database administrator remains trusted.
DB-backed quotas survive process restarts; an upstream service is still needed
for volumetric DDoS protection. Database/host compromise is outside these controls.

PostgreSQL stores active sessions and quota windows, so an unavailable database
fails authentication and new work closed. Daily token reservations deliberately
overestimate usage and are not a currency charge. Price fields stay `unknown`
unless an operator provides a valid pricing configuration.

Automated evidence lives in `tests/test_public_access.py`, `tests/test_operations.py`,
`security/public-v1/cases.json`, the browser suite, and `scripts/public_smoke.py` /
`scripts/recovery_smoke.py`. The release report distinguishes local verified TLS
from a real public domain certificate and external deployment.

References: [OWASP authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html),
[session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
