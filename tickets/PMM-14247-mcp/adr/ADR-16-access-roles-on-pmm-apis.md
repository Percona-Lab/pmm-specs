# ADR-16: Access Roles on PMM's service-scoped APIs

- Status: Proposed
- Date: 2026-10-24
- Tickets: PMM-14247, PMM-15531, PMM-15536
- Implemented: not yet (phase 4)

## Context

Access Roles filter two sources today. Metrics: vmproxy injects the caller's filters as `extra_filters[]` into VictoriaMetrics queries. QAN: qan-api2 parses them with Prometheus's selector parser (`qan-api2/models/reporter.go:808`) and turns them into query conditions. Both read the filters from the `X-Proxy-Filter` header, which `auth_request` sets for paths in `lbacPrefixes` (`managed/services/grafana/auth_server.go`) and which nginx forwards to every upstream.

pmm-managed's own APIs, and Grafana's alerting API, apply no Access Role filter. MCP needs three such sources: the inventory (ADR-08), Advisor results (ADR-18) and alerts (ADR-17). ADR-03 keeps authorization out of MCP.

## Options

1. Each MCP tool narrows its own results. This breaks ADR-03, and every other caller of these APIs stays unscoped.
2. Each API applies the filters with its own code.
3. One matcher in pmm-managed, used by every service-scoped API, with the same meaning as for metrics and QAN.

## Decision

Option 3.
- **Plumbing.** The paths are added to `lbacPrefixes`, so `auth_request` sets `X-Proxy-Filter` for them. pmm-managed's gRPC gateway forwards the header into gRPC metadata; it has no header matcher today, so one is added [I].
- **Meaning.** Each filter is a series selector, parsed as qan-api2 parses it. An item is visible when its label set matches at least one of the caller's selectors. No header means no filtering: Access Control is off, or one of the caller's roles has no filter. A selector that can't be parsed refuses the request.
- **Label set of an item:**
  - a service: its labels (`UnifiedLabels` in `managed/models/service_model.go`) plus its node's;
  - a node: its own labels; a node that hosts a visible service is visible too;
  - an Advisor result: the labels of its service;
  - an alert: its own labels.
- **Missing labels** behave as in PromQL: `service_name="a"` doesn't match an item without `service_name`; `service_name!="a"` does.
- **Counts and summaries** cover visible items only.

## Consequences

- A filter means the same for metrics, QAN, the inventory, Advisors and alerts.
- MCP still authorizes nothing (ADR-03); any other caller of these APIs, the PMM UI included, gets the same scoping.
- PMM-wide change: an Editor with a restricted role sees only their services' Advisor results in the UI too.
- An item with none of the filtered labels, such as a server-level alert, is hidden from a restricted caller.
- Every new service-scoped read API joins `lbacPrefixes` and uses the matcher.
- Tests: the matcher against qan-api2's selector cases, and the Access Control matrix (spec §11).
