# ADR-08: Service list from Access-Role-filtered metric series

- Status: Accepted (2026-11-05), after the review in pmm-specs#4
- Date: 2026-10-22, revised 2026-10-24, 2026-11-02, 2026-11-03 and 2026-11-06
- Tickets: PMM-14247, PMM-15531, PMM-15536
- Implemented: Viewer rules in `PMM-MCP-GA` (percona/pmm#5942, D3 in `DECISIONS.md`), to be removed; the service list from series not yet (plan 06)

## Context

`pmm_inventory` is the entry point of every triage: the model needs a `service_id` before anything else. Every other tool resolves a service's engine through the same list. `auth_server.go` maps all of `/v1/inventory` to Admin. #5942 added two `methodRules` entries so that a Viewer can call `GET /v1/inventory/services` and `GET /v1/inventory/nodes`.

The inventory API applies no Access Role filter. With those rules alone, a Viewer whose role allows one service lists every service, with its address and port. The rules are not on `main`.

## Options

1. Keep the inventory Admin-only; MCP needs an Admin token. Rejected: the endpoint is meant for Viewer tokens.
   Editor as the minimum role was rejected too: an Editor token can also write alert rules and Advisor checks (ADR-18).
2. Let Viewers read the inventory, unfiltered (#5942 as it stands). Rejected: it shows a restricted caller every service.
3. Let Viewers read the inventory, filtered by Access Roles in pmm-managed (ADR-16). Rejected for this epic: it is a PMM-wide change to the inventory API and the nginx and gateway plumbing in front of it, which MCP doesn't need (ADR-16, deferred).
4. Build the service list from the metric series the caller can read, which vmproxy already filters by the caller's Access Roles.

## Decision

Option 4. `pmm_inventory`, and every service lookup in MCP, use the services and nodes seen in every `up` series of the look-back window (spec §8), read through the Grafana datasource proxy (ADR-09). The series are grouped by the labels scrape targets carry (`service_id`, `service_name`, `service_type`, `node_id`, `node_name`, `environment`, `cluster`; `MergeLabels`, `scrape_configs.go:160`) [V]; only `service_id` is required, because empty labels are removed before they reach VictoriaMetrics (`UnifiedLabels`, `service_model.go:114`) [V]. Every row with a `service_id` is a service of any type; every node named in any row, node_exporter's included, is a node of the list. `last_seen` is the newest `up` sample time, whatever its value. The caller sees the services it sees on dashboards. A `service_id` outside that list answers `not_found` (ADR-03).

The Viewer rules from #5942 for `GET /v1/inventory/services` and `/nodes` are removed; the inventory API stays Admin-only.

## Consequences

- A Viewer service-account token covers every tool; `pmm_advisors` is out of the Tech Preview (ADR-18).
- No PMM-wide permission change: the inventory API keeps its Admin rule. PMM-15536 is not needed by MCP.
- `pmm_inventory` reports no address or port. A target scraped with `up=0` stays listed with a current `last_seen`. A service leaves the list only when no `up` sample arrived in the look-back window, for example when its pmm-agent stopped; a removed service leaves it the same way. Alerts are narrowed with a 7-day list instead (ADR-17). A longer look-back would keep it, at the cost of a larger query behind every tool call; plan 06 measures it, and the value lives in spec §8.
- The list query's cost, measured by plan 06 as Admin through the datasource proxy on plan 05's load-test server (4 cores, 53 MySQL services plus PMM's own PostgreSQL: 54 services, 59 rows), 20 runs per look-back:
  - with about 2 days of data, a p95 of 52 ms over 1 hour, 57 ms over 24 hours and 83 ms over 7 days;
  - with 6 days of data (2026-11-13), p50 and p95 of 43 and 50 ms over 1 hour, 53 and 60 ms over 24 hours, and 78 and 92 ms over 7 days.

  The 7-day look-back stays under 100 ms, so spec §8's look-backs stand.
- QAN can show a service the list lacks; detail, explain and schema then answer `not_found` (spec §13).
- With Access Control off, or a role without a filter, the list is every service with metrics, as on dashboards.
