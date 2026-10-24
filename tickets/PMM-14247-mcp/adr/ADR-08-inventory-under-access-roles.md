# ADR-08: Inventory reads under Access Roles

- Status: Proposed
- Date: 2026-10-22, revised 2026-10-24
- Tickets: PMM-14247, PMM-15531, PMM-15536
- Implemented: Viewer rules in `PMM-MCP-GA` (percona/pmm#5942, D3 in `DECISIONS.md`); Access Role filtering not yet (phase 4)

## Context

`pmm_inventory` is the entry point of every triage: the model needs a `service_id` before anything else. Every other tool resolves a service's engine through the same inventory list. `auth_server.go` maps all of `/v1/inventory` to Admin. #5942 added two `methodRules` entries so that a Viewer can call `GET /v1/inventory/services` and `GET /v1/inventory/nodes`.

The inventory API applies no Access Role filter. With those rules alone, a Viewer whose role allows one service lists every service, with its address and port. The rules are not on `main`.

## Options

1. Keep the inventory Admin-only; MCP needs an Admin token.
2. Let Viewers read the inventory, unfiltered (#5942 as it stands).
3. Let Viewers read the inventory, filtered by Access Roles in pmm-managed (ADR-16).
4. Build the service list from LBAC-filtered `up` series instead of the inventory API.

## Decision

Option 3. `GET /v1/inventory/services` and `GET /v1/inventory/nodes`, and the single-object paths under them, stay readable by Viewers and apply ADR-16's matcher. Writes stay Admin, and so does `GET /v1/inventory/agents`, because agent records carry connection configuration. MCP keeps using the inventory API for the service list and for every service lookup; a `service_id` outside the caller's list answers `not_found`.

Option 4 was this record's first revision. It lists only services with recent series and drops address and port; it was chosen to avoid a PMM-wide change. ADR-16 makes that change anyway for Advisors and alerts, so the inventory uses it too.

## Consequences

- A Viewer service-account token covers every tool except `pmm_advisors` (Editor, ADR-18).
- This is a PMM-wide permission change (PMM-15536), with Access Roles applied. It affects every Viewer.
- Editor was rejected because an Editor token can also write alerting templates.
- `pmm_inventory` also reports each service's scrape health from its `up` series, read through the datasource proxy like the versions (ADR-09).
- The Viewer rules must not reach `main` without the filter. Both land before the merge back (spec §10).
