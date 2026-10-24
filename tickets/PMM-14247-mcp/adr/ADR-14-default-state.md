# ADR-14: Default state at release

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15532
- Implemented: not yet (phase 5)

## Context

ADR-06 ships `/mcp` off. PMM-15532 asks for the default to be decided on evidence, not convenience. A server that upgrades should not gain a new LLM-facing endpoint without an admin choosing it.

## Options

1. Keep it off for this release; decide again next release.
2. Decide in phase 5 against fixed conditions, and turn it on when they all hold.
3. Turn it on at release unconditionally.

For a default that turns on, upgraded servers can either keep their current effective state (off) or take the new default.

## Decision

Option 2. Phase 5 turns `PMM_ENABLE_MCP` on by default only if all of these hold:
- the formal security review passed, with no open high or critical finding;
- PMM-15534 and PMM-15703 are fixed on `main`;
- ADR-13's permissions have shipped;
- the Viewer-token triage passes on a Feature Build for MySQL, PostgreSQL and MongoDB.

Otherwise it stays off and is decided again next release. `PMM_MCP_RAW_SQL` stays `false` either way.

A new default applies to **new installations only**. Upgraded servers on which an admin never set the value keep it off. The settings store the value as an optional field and fall back to the default when it is unset; the upgrade must write an explicit `false` for existing installations. A plain SQL migration can't do this alone, because a new installation runs every migration too; the phase 5 plan chooses the mechanism.

Whether a default-on release is still labelled Tech Preview is a product decision, recorded on PMM-15532.

## Consequences

- The default follows evidence, and the conditions are checkable.
- No upgraded server gains the endpoint silently. New installations get it if the conditions hold.
- Two populations of servers behave differently until admins choose; the release notes say how to enable or disable it.
- Telemetry (phase 5) measures use after release and informs the next decision.
