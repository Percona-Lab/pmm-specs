# ADR-01: In-server endpoint

- Status: Accepted (2026-11-05), after the review in pmm-specs#4
- Date: 2026-10-22, revised 2026-11-02
- Tickets: PMM-14247, PMM-15527, PMM-15532
- Implemented: `PMM-MCP-GA`, percona/pmm#5942

## Context

AI clients need a way to read PMM data within the caller's own permissions. Three attempts existed and none had merged: an in-server endpoint bundled with an AI chat backend (#4045), a standalone Go server (percona/pmm-mcp, empty apart from a README), and an in-server endpoint contributed by Sixta Systems (#5942).

## Options

1. A standalone MCP server, run as a sidecar or on the client, calling PMM's API. It would work with servers already deployed, without an upgrade, add no endpoint to the server, and release on its own schedule. Rejected: every user installs, configures and updates a second component, and it has to track PMM's API version by version.
2. An endpoint inside pmm-managed.
3. Both. Rejected: two implementations of one tool surface to keep in step.

## Decision

Option 2. `/mcp` is served by pmm-managed and exposed by nginx `location /mcp`.

## Consequences

- Users install nothing extra; the endpoint ships with the server and moves with the API it calls.
- One tool surface to maintain.
- Every server gains a new externally reachable endpoint. ADR-06 (off by default) and ADR-10 (nginx only) contain that.
- Servers older than the release that ships `/mcp` get no MCP; users upgrade.
- The MCP code follows pmm-managed's release and review cycle.
- percona/pmm-mcp is superseded. Phase 5 archives it and answers its contributors.
