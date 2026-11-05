# ADR-14: Default state at release

- Status: Accepted (2026-11-05), after the review in pmm-specs#4
- Date: 2026-10-22, revised 2026-10-24
- Tickets: PMM-14247, PMM-15532
- Implemented: nothing to change; `PMM-MCP-GA` already defaults to off (ADR-06)

## Context

ADR-06 ships `/mcp` off. PMM-15532 asks for the default to be decided on evidence, not convenience. The endpoint ships as a Tech Preview, and there is no data yet on how it is used.

## Options

1. Keep it off for this release; decide again for a later release.
2. Decide in phase 5 against fixed conditions, and turn it on when they all hold, for new installations only. Rejected: new and upgraded servers would have to differ, which a plain migration can't express.
3. Turn it on at release unconditionally. Rejected: before the security review's findings and any usage data.

## Decision

Option 1. `PMM_ENABLE_MCP` stays `false` in the release that lands `PMM-MCP-GA`, on new and upgraded servers alike; admins opt in. `PMM_MCP_RAW_SQL` stays `false`.

A later ADR decides the default for the release that drops the Tech Preview label, using the telemetry from phase 5 and the findings of the security review.

## Consequences

- No server gains the endpoint without an admin choosing it.
- No upgrade logic.
- Adoption depends on admins finding the setting; the release notes and `mcp.md` say how to enable it.
- Telemetry measures use after release and informs the next decision.
