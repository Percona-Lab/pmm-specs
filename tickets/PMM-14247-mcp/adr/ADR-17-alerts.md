# ADR-17: Alerts

- Status: Proposed
- Date: 2026-10-24, revised 2026-10-26
- Tickets: PMM-14247, PMM-15790, PMM-15531
- Implemented: not yet (API in phase 4, tool in phase 2b)

## Context

PMM alerting is Grafana's alerting; PMM adds rule templates (`/v1/alerting`). Firing alerts are the first thing to look at in a triage. Grafana's alert APIs apply Grafana's own permissions, by folder, but no Access Role filter. pmm-managed already calls Grafana's alerting API with the caller's headers (`managed/services/grafana/client.go:732`).

## Options

1. MCP reads Grafana's alert API directly: no Access Role filter.
2. The Grafana fork filters alerts by the `X-Proxy-Filter` header.
3. pmm-managed serves a read API that fetches alerts from Grafana with the caller's credentials and filters them (ADR-16).

## Decision

Option 3.
- **API.** A new read endpoint, `GET /v1/alerting/alerts`, in pmm-managed, at Viewer. It reads the current alerts from Grafana with the caller's headers, so Grafana's folder permissions apply first, then ADR-16's matcher on each alert's labels. It reports firing alerts, silenced or not.
- **Grafana endpoint, settled before this ADR is accepted.** The candidates are Grafana's Alertmanager API (`/api/alertmanager/grafana/api/v2/alerts`) and its Prometheus-style API (`/api/prometheus/grafana/api/v1/alerts`) [I]. On a Feature Build, record here which one is used, what a Viewer gets from it, and how folder permissions narrow it.
- **Tool.** `pmm_alerts` returns each alert's name, severity, labels, summary and description, start time, whether it is silenced and until when, and a link to it in PMM. It filters by service, node and severity, and pages (ADR-11).
- **Ownership.** An alert belongs to the service its labels name. One with no service labels, such as a server-level alert or one whose rule aggregates them away, belongs to no service and is hidden from restricted callers (ADR-16), whichever form their filter takes.
- **Untrusted text.** Summaries and descriptions are written by rule authors and may name other services. They are returned as written, marked untrusted in the contract (ADR-11), and never used for matching.
- **Read only.** Silencing, acknowledging and editing rules stay out (ADR-05).

Option 2 would scope the PMM UI's alert list too, but it needs a change and a release of the Grafana fork. Option 3 stays in percona/pmm, next to the other filtered APIs.

## Consequences

- Alerts are scoped like metrics and QAN, for MCP and for any other caller of the endpoint.
- Grafana's own alert list in the PMM UI is unchanged; scoping it needs option 2, outside this epic.
- A restricted caller sees no server-level alerts.
- Current alerts only; alert history is out.
- Tests: a restricted caller with a positive and with a negative filter, against alerts with the service's labels, another service's labels, and none.
