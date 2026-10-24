# ADR-08: Viewer reads the services and nodes inventory

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15536
- Implemented: `PMM-MCP-GA`, percona/pmm#5942 (D3 in `DECISIONS.md`)

## Context

`pmm_inventory` is the entry point of every triage: the model needs a `service_id` before anything else. `auth_server.go` maps all of `/v1/inventory` to Admin, so a least-privilege client would need an Admin token, which also allows inventory writes. Viewers already see every service and node name on dashboards and in QAN filters.

## Options

1. Keep inventory Admin-only.
2. Allow Viewer to read services and nodes.
3. Allow Editor to read them.

## Decision

Option 2. Two `methodRules` entries: `GET /v1/inventory/services` and `GET /v1/inventory/nodes` at `viewer`. Writes stay Admin through the existing prefix rule, and so does `GET /v1/inventory/agents`, because agent records carry connection configuration. Because `resolveRule` walks prefixes, a Viewer can also read a single service or node by ID; the fields are the same as in the lists.

## Consequences

- A Viewer service-account token covers every tool.
- This is a PMM-wide permission change, not only an MCP one (PMM-15536). It applies to every Viewer.
- Editor was rejected because an Editor token can also write alerting templates.
- With Access Control on, ADR-13 adds the `inventory:read` permission on top of this rule.
