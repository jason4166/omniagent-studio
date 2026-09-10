# ADR 0005: Fixed local HTTP and MCP adapters

Status: accepted for v1 delivery.

The generic HTTP adapter accepts an administrator-owned connector with one fixed host, port,
path, GET/POST method, input/output schema, safe headers, timeout and response limit. The model
only supplies schema-validated business parameters. The public API can select approved adapter
IDs, not invent URLs, commands, headers or arbitrary endpoints. The application enables only
the loopback/Docker mock service. Connector credentials, when configured, are environment
references, never exported credential values.

The adapter resolves the approved host and dials the checked IP without a second DNS lookup.
Metadata, link-local, multicast and unspecified addresses are always denied. A private/loopback
exception is explicit for the administrator-fixed local mock host. Redirects, compression,
non-JSON, oversized responses and invalid output schemas fail closed. Timeouts include both
transport timeouts and a total response-reading deadline. No transport-level retry is implicit.
TLS and arbitrary public Internet connectors are outside the local mock release scope.

Mock POST endpoints independently check the PostgreSQL approval, exact payload, active session
and execution reservation. The operation key identifies the same transactional mock effect even
when the caller loses a response. No real CRM, email, payment or external business system is used.

MCP uses the locked official Python SDK v1.30.0, local stdio, protocol negotiated as 2025-11-25.
The installed v1 API was verified directly; current upstream main documents a different v2 API.
Only the fixed Python module `omniagent.mcp_server` can launch, with a minimal inherited environment.
It exposes `lookup_product` and `catalog://policy`. Remote names and schema shape are checked;
metadata cannot lower local risk. Both `catalog.lookup_product` and `catalog.resource` are internal
Registry entries subject to Profile allowlists, roles, approval, budgets, timeout and audit.

The OpenAPI importer supports only preapproved GET query parameters and required POST JSON bodies.
It verifies path, method, operation ID and the business schema against administrator contracts.
Remote `$ref`, servers, path/header parameters, unsupported methods and duplicate IDs are rejected.

References: [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[MCP 2025-11-25 specification](https://modelcontextprotocol.io/specification/2025-11-25).

Evidence: HTTP contract/security tests, real local MCP calls, and real loopback HTTP workflows in
`tests/test_application.py`. The Fake provider is deterministic demonstration logic; its results
measure the platform workflow and validation, not learned semantic reasoning quality.
