# ADR-06: Off by default, switched per request

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15528
- Implemented: `PMM-MCP-GA`, percona/pmm#6068 (D5 in `DECISIONS.md`)

## Context

`/mcp` is a new, externally reachable, LLM-driven surface. An operator must be able to turn it off at once, on a running server.

## Options

1. On by default.
2. Off by default, read at start-up.
3. Off by default, read on every request.

## Decision

Option 3. `PMM_ENABLE_MCP` (also the `enable_mcp` field of the settings API) defaults to `false`. The handler reads the setting on every request and answers 404 when it is off, so the endpoint is invisible and can be disabled without a restart. A wiring mistake that supplies no setting also means off. The state shows in `GET /v1/server/settings/readonly`.

## Consequences

- Nobody gets the endpoint without choosing it.
- The setting doubles as a kill switch.
- One settings read per request.
- Whether the default changes at release is ADR-14's decision.
