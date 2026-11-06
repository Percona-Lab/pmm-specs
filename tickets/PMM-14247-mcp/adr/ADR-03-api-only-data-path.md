# ADR-03: Data only through the public API; MCP narrows, never widens

- Status: Accepted (2026-11-05), after the review in pmm-specs#4
- Date: 2026-10-22, revised 2026-11-02 and 2026-11-06
- Tickets: PMM-14247, PMM-15528, PMM-15529, PMM-15531, PMM-15790
- Implemented: the API-only path in `PMM-MCP-GA` (percona/pmm#5942); the narrowing not yet (plans 04, 06, 07)

## Context

An MCP tool can reach PMM data in three ways: by querying the stores directly (ClickHouse, VictoriaMetrics, PostgreSQL), by calling pmm-managed's internal Go services, or by calling PMM's public REST API. A tool that reads the stores, or reuses one shared credential, bypasses per-caller authorization and breaks when a store's schema changes.

## Options

1. Query the stores directly. Rejected: no per-caller authorization, and the tools break when a store's schema changes.
2. Call internal services in-process. Rejected: the internal services authorize nothing themselves; MCP would have to repeat the auth server's rules.
3. Call the public REST API on the nginx loopback with the caller's own credentials.

## Decision

Option 3. Every tool call goes to `http://127.0.0.1:8080/` (nginx) and copies the caller's credentials onto the backing request, as `Authorization` and `Cookie` in the form ADR-10 gives. nginx `auth_request` then authorizes each backing call against the caller's role and adds LBAC filters where it applies them. The MCP package holds no credentials of its own.

**MCP never widens access; it narrows.** Every service lookup, live action, resolve-first candidate, query detail and alert is limited to the caller's service list: the services in the metric series the caller can read, which vmproxy filters by the caller's Access Roles (ADR-08). A `service_id` outside that list answers `not_found`, and no error names a service outside it. The backing API stays the authority. For APIs that don't apply Access Roles themselves (Grafana's alerts, ADR-17), this narrowing makes MCP's results consistent with the caller's other data; it is **not a security boundary**, because the same caller can still read those APIs unfiltered with the same credentials. Other records refer to this as "narrowed, not filtered". Applying Access Roles to them is PMM-wide work outside this epic (ADR-16).

## Consequences

- The MCP layer can never do more than the same token can do with `curl`. Fixes to PMM's authorization apply to MCP automatically.
- The tools survive backend re-architecture as long as the `/v1/` contract holds.
- Each tool call costs one or more extra loopback HTTP round trips.
- Gaps in the REST API's own authorization are inherited too; they are fixed in the API, not in MCP. MCP's narrowing hides them in its own results but doesn't close them.
- Credentials pass through pmm-managed in memory. MCP's code never logs them; whether any hop on the path does is part of the security review (spec §10).
