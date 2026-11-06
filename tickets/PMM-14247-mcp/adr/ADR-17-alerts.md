# ADR-17: Alerts

- Status: Proposed
- Date: 2026-10-24, revised 2026-10-26, 2026-11-02, 2026-11-03, 2026-11-04 and 2026-11-06
- Tickets: PMM-14247, PMM-15790
- Implemented: not yet (plan 07)

## Context

PMM alerting is Grafana's alerting; PMM adds rule templates (`/v1/alerting`). Firing alerts are a common starting point for triage, and without them an AI client can't answer "what is wrong right now". Grafana's Prometheus-style rules API applies Grafana's folder permissions: it returns only the rules in folders the caller can read, each with its alert instances. Grafana's alert list endpoints are not folder-scoped. None of them applies an Access Role filter [V]. PMM's own alert page reads the rules API (`ui/apps/pmm/src/api/alerting.ts`) [V]. pmm-managed already calls Grafana's alerting API with the caller's headers (`managed/services/grafana/client.go:732`) [V].

## Options

1. MCP reads Grafana's alert API directly, with the caller's credentials, and narrows the result to the caller's service list (ADR-03).
2. The Grafana fork filters alerts by the caller's Access Roles. Rejected for this epic: a change and a release of the Grafana fork.
3. pmm-managed serves a read API that fetches alerts from Grafana and filters them with a PMM-wide matcher (ADR-16). Rejected for this epic: it needs ADR-16's PMM-wide plumbing, which is deferred.

## Decision

Option 1.
- **Source.** `pmm_alerts` reads the firing alerts from Grafana's rules API (`/graph/api/prometheus/grafana/api/v1/rules`) through nginx on loopback, with the caller's `Authorization` and `Cookie`, like every backing call (ADR-03). That API is folder-scoped, so `pmm_alerts` shows a Viewer what PMM's own alert page shows. The alert list endpoints (`/graph/api/alertmanager/grafana/api/v2/alerts`, `/graph/api/prometheus/grafana/api/v1/alerts`) are not folder-scoped, and never supply the list.
- **Silence state** comes from Grafana's Alertmanager (its alerts and silences) and is joined by rule UID only: it marks an alert of a rule the rules API returned, and an Alertmanager alert whose rule UID isn't among those rules adds nothing. Labels never join on their own.
- Plan 07 Task 1 checks both on a Feature Build, with what a Viewer and an Editor get, and records the field mapping here before this ADR is accepted. No pmm-managed API and no Grafana fork change.
- **Narrowing.** Against the caller's list (ADR-08), which holds services and nodes of every type:
  - An alert that names a service is kept when every service label it carries is in the list (`service_id` against the list's service IDs, `service_name` against its service names), whatever node it names. PMM's `*_down` templates aggregate `pmm_managed_inventory_agents`, whose `node_name` is the node the exporter's pmm-agent runs on (`managed/services/inventory/inventory_metrics.go:155-161`), while the `up` series behind the list carry the service's own node (`managed/services/victoriametrics/prometheus.go:102-109`) [V]. RDS and Azure exporters always run on PMM Server's own pmm-agent (`managed/services/management/rds.go:293`, `azure_database.go:199`) [V], so those services' down alerts name PMM Server's node (`pmm-server`), which a restricted caller's list usually lacks.
  - An alert that names no service but names a node is kept when every node label it carries is in the list (`node_id` against its node IDs, `node_name` against its node names).
  - An alert with none of these labels, such as a server-level alert or one whose rule aggregates them away, is kept: Grafana's alert list shows it to the same caller.
  - So is every alert of PMM's own rules, whatever it names: the HA and PMM Server component rules PMM provisions (`managed/services/alerting/provisioning_catalog.go`), whose `node_id`, `node_name` and `service_name` name PMM Server replicas (`PMM_HA_NODE_ID`) and components (a scrape job such as `clickhouse`), not services or nodes in the list. They are identified by rule UID or provenance, never by a label, since a rule's author sets its labels; plan 07 Task 1 records which of the two the rules API carries.
- **Look-back for alerts.** The list used to narrow alerts covers 7 days of `up` samples, not the 1 hour of the other tools (ADR-08). A service whose pmm-agent went silent sends no `up` samples, yet its alerts, the one saying it is down included, are what a triage needs; with the 7-day list they stay for 7 days.
- Narrowed, not filtered: not a security boundary (ADR-03). Filtering alerts by Access Role is PMM-wide work (ADR-16, deferred).
- **Tool.** `pmm_alerts` returns firing alerts, silenced or not, with name, severity, labels, summary and description, start time, whether it is silenced and until when, and a link to it in PMM. It filters by service, node and severity, and pages (ADR-11). The tool description and every result, an empty one included, say "Currently firing alerts only; resolved alerts are not shown."
- **Untrusted text.** Summaries and descriptions are written by rule authors and may name other services. They are returned as written, marked untrusted in the contract (ADR-11), and never used for narrowing.
- **Read only.** Silencing, acknowledging and editing rules stay out (ADR-05).

## Consequences

- An AI client sees the firing alerts of its services, and the server-level ones, with no new PMM API.
- A restricted caller still reads every alert of the folders it can read through Grafana's API and UI, as today. An alert of a rule in a folder it can't read doesn't reach it through MCP either.
- MCP doesn't drop server-level alerts.
- A service that sent no `up` sample for 7 days leaves the list used for alerts, so its alerts are dropped after 7 days of silence, including the one saying it is down. The 7-day list query reads more than the 1-hour one; plan 06 measures both.
- Alerts evaluated by VMAlert from PMM's rule files, visible only to Admins, are out of scope.
- Currently firing alerts only, and every result says so, so an empty list is never read as "nothing happened". Reading Grafana's alert state history for a time window, narrowed the same way, is a follow-up ticket outside this epic.
- Tests: a restricted caller, with a positive and with a negative filter, against alerts with the service's labels, another service's labels, node labels only, and none; and the `mysql_down` template, which aggregates `by (service_id, service_name, node_name)`, under a role on `environment`, a label the alert doesn't carry, for a service whose pmm-agent runs on another node (an RDS service, `node_name="pmm-server"`): kept, because the service it names is in the list; and, for a restricted caller, `pmm_ha_node_unreachable` (`node_id` = `PMM_HA_NODE_ID`) and `pmm_clickhouse_down` (`service_name="clickhouse"`) on HA, and `pmm_grafana_down` on a standalone server: kept, as alerts of PMM's own rules; a user's rule labelled `pmm_provisioned="1"` that names a service outside the list: dropped; and, for a Viewer, a rule in a folder without Viewer access, silenced or not: absent.
