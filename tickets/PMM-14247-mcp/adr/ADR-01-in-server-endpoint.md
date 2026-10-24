# ADR-01: In-server endpoint

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15527, PMM-15532
- Implemented: `PMM-MCP-GA`, percona/pmm#5942

## Context

AI clients need a safe way to read PMM data. Three attempts existed and none had merged: an in-server endpoint bundled with an AI chat backend (#4045), a standalone Go server (percona/pmm-mcp, empty apart from a README), and an in-server endpoint contributed by Sixta Systems (#5942). PMM's own AI features will need the same data-access layer.

## Options

1. A standalone MCP server, run as a sidecar or on the client, calling PMM's API.
2. An endpoint inside pmm-managed.
3. Both.

## Decision

Option 2. `/mcp` is served by pmm-managed and exposed by nginx `location /mcp`.

## Consequences

- Users install nothing extra; the endpoint ships with the server and moves with the API it calls.
- One tool surface to maintain, which PMM's own AI features can later consume.
- Every server gains a new externally reachable endpoint. ADR-06 (off by default) and ADR-10 (nginx only) contain that.
- The MCP code follows pmm-managed's release and review cycle.
- percona/pmm-mcp is superseded. Phase 5 archives it and answers its contributors.
