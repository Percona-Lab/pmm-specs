# ADR-17: Alerts

- Status: Proposed
- Date: 2026-10-24
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
- **API.** A new read endpoint, `GET /v1/alerting/alerts`, in pmm-managed, at Viewer. It reads the current alerts from Grafana's Alertmanager API with the caller's headers, so Grafana's folder permissions apply first, then ADR-16's matcher on each alert's labels. It reports firing alerts, silenced or not. The Grafana endpoint is chosen in the phase 4 plan [I].
- **Tool.** `pmm_alerts` returns each alert's name, severity, labels, summary and description, start time, whether it is silenced, and a link to it in PMM. It filters by service, node and severity, and pages (ADR-11).
- **Read only.** Silencing, acknowledging and editing rules stay out (ADR-05).

Option 2 would scope the PMM UI's alert list too, but it needs a change and a release of the Grafana fork. Option 3 stays in percona/pmm, next to the other filtered APIs.

## Consequences

- Alerts are scoped like metrics and QAN, for MCP and for any other caller of the endpoint.
- Grafana's own alert list in the PMM UI is unchanged; scoping it needs option 2, outside this epic.
- An alert whose labels match none of a restricted caller's filters is hidden, server-level alerts included.
- Current alerts only; alert history is out.
- Summaries and descriptions are written by the rule author and returned as written (ADR-07).
