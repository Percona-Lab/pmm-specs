# ADR-03: Data only through the public API

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15528
- Implemented: `PMM-MCP-GA`, percona/pmm#5942

## Context

An MCP tool can reach PMM data in three ways: by querying the stores directly (ClickHouse, VictoriaMetrics, PostgreSQL), by calling pmm-managed's internal Go services, or by calling PMM's public REST API. PMM's earlier AI experiments wrote ClickHouse SQL with one shared service-account token: no per-caller authorization, and silent breakage whenever the QAN schema changed.

## Options

1. Query the stores directly.
2. Call internal services in-process.
3. Call the public REST API on the nginx loopback with the caller's own credentials.

## Decision

Option 3. Every tool call goes to `http://127.0.0.1:8080/` (nginx) and copies the caller's `Authorization` and `Cookie` headers verbatim onto the backing request. nginx `auth_request` then authorizes each backing call against the caller's role and adds LBAC filters where it applies them. The MCP package authorizes nothing itself and holds no credentials of its own.

## Consequences

- The MCP layer can never do more than the same token can do with `curl`. Fixes to PMM's authorization apply to MCP automatically.
- The tools survive backend re-architecture as long as the `/v1/` contract holds.
- Each tool call costs one or more extra loopback HTTP round trips.
- Gaps in the REST API's own authorization are inherited too; they are fixed in the API, not in MCP.
- Credentials pass through pmm-managed in memory and must never be logged (security review, phase 5).
