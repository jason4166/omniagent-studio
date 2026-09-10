# ADR 0006: Typed browser client and durable event replay

Status: accepted.

Vue 3, TypeScript, Element Plus and Vite implement the local workspace. A single typed API
client owns every HTTP request. Credentials are server references in configuration, never
Provider keys in the browser. The visible identity selector is explicitly a local development
feature. Changing identity destroys the previous view and aborts its subscription.

Authenticated fetch streaming is used for SSE because the bearer identity belongs in a header.
Events have a version, thread/run identity, stable event_id and monotonically increasing sequence.
The browser rejects foreign identities, schema changes and sequence gaps; duplicate replay is
ignored. On reconnection it requests the last consumed cursor. Subscriptions only read durable
events and never resume or execute an operation. Failed POST requests keep their original
idempotency key; the approval card additionally disables repeated clicks while a decision runs.

The service validates a complete grounded answer before publishing 64-character message chunks.
This is validated-answer streaming, with live node/approval events, rather than native incremental
Provider token streaming. It intentionally avoids exposing unvalidated claims before citation
checks. Streaming connections rotate after 45 seconds and reconnect with the durable cursor.
Disconnected clients do not cancel an authorized run. Explicit cancellation uses the session API.

All document text, argument values, tool results and errors render as text. Citation buttons resolve
an internal chunk identifier through an authenticated, KB-filtered endpoint; document-provided
URLs never become navigation targets. Approval edits are sent through the same server schema,
RBAC, risk, version and replay checks as approval of the original proposal.

Admin components load on demand. Element Plus components are imported on demand; the common
stylesheet is local. Dependencies are fixed by package-lock.json. Development verification uses
Node 24.15.0, vue-tsc, ESLint, Prettier, Vitest and real Chromium/Playwright.

References: [Vue TypeScript](https://vuejs.org/guide/typescript/overview),
[Element Plus quickstart](https://element-plus.org/en-US/guide/quickstart.html),
[Vite tooling](https://vite.dev/guide/).
