# ADR-17: Alerts

- Status: Proposed
- Date: 2026-10-24, revised 2026-10-26 and 2026-11-02
- Tickets: PMM-14247, PMM-15790
- Implemented: not yet (plan 07)

## Context

PMM alerting is Grafana's alerting; PMM adds rule templates (`/v1/alerting`). Firing alerts are a common starting point for triage, and without them an AI client can't answer "what is wrong right now". Grafana's alert APIs apply Grafana's own permissions, by folder, but no Access Role filter. pmm-managed already calls Grafana's alerting API with the caller's headers (`managed/services/grafana/client.go:732`) [V].

## Options

1. MCP reads Grafana's alert API directly, with the caller's credentials, and narrows the result to the caller's service list (ADR-03).
2. The Grafana fork filters alerts by the caller's Access Roles. Rejected for this epic: a change and a release of the Grafana fork.
3. pmm-managed serves a read API that fetches alerts from Grafana and filters them with a PMM-wide matcher (ADR-16). Rejected for this epic: it needs ADR-16's PMM-wide plumbing, which is deferred.

## Decision

Option 1.
- **Source.** `pmm_alerts` reads the current alerts from Grafana through nginx on loopback, with the caller's `Authorization` and `Cookie`, like every backing call (ADR-03), so Grafana's folder permissions apply [I, settled in plan 07]. The candidates are Grafana's Alertmanager API (`/graph/api/alertmanager/grafana/api/v2/alerts`) and its Prometheus-style API (`/graph/api/prometheus/grafana/api/v1/alerts`) [I]. Plan 07 settles which one on a Feature Build, with what a Viewer and an Editor get from it, and records the answer here before this ADR is accepted. No pmm-managed API and no Grafana fork change.
- **Narrowing.** An alert is kept only if every service it names (`service_id` against the list's service IDs, `service_name` against its service names) and every node it names (`node_id`, `node_name`, likewise) is in the caller's list (ADR-08), which holds services and nodes of every type. An alert with none of these labels, such as a server-level alert or one whose rule aggregates them away, is kept: Grafana's alert list shows it to the same caller.
- Narrowed, not filtered: not a security boundary (ADR-03). Filtering alerts by Access Role is PMM-wide work (ADR-16, deferred).
- **Tool.** `pmm_alerts` returns firing alerts, silenced or not, with name, severity, labels, summary and description, start time, whether it is silenced and until when, and a link to it in PMM. It filters by service, node and severity, and pages (ADR-11).
- **Untrusted text.** Summaries and descriptions are written by rule authors and may name other services. They are returned as written, marked untrusted in the contract (ADR-11), and never used for narrowing.
- **Read only.** Silencing, acknowledging and editing rules stay out (ADR-05).

## Consequences

- An AI client sees the firing alerts of its services, and the server-level ones, with no new PMM API.
- A restricted caller still reads every alert through Grafana's API and UI, as today.
- MCP doesn't drop server-level alerts.
- A service that sent no `up` sample in the look-back window leaves the caller's list (ADR-08), so its alerts are dropped, including those that fire because its pmm-agent is silent.
- Alerts evaluated by VMAlert from PMM's rule files, visible only to Admins, are out of scope.
- Current alerts only; alert history is out.
- Tests: a restricted caller, with a positive and with a negative filter, against alerts with the service's labels, another service's labels, node labels only, and none.
