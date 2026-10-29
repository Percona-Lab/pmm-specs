# ADR-16: Access Roles on PMM's service-scoped APIs

- Status: Proposed
- Date: 2026-10-24, revised 2026-10-26
- Tickets: PMM-14247, PMM-15531, PMM-15536
- Implemented: not yet (phase 4)

## Context

Access Roles filter two sources today. Metrics: vmproxy injects the caller's filters as `extra_filters[]` into VictoriaMetrics queries. QAN: qan-api2 parses them with Prometheus's selector parser (`qan-api2/models/reporter.go:808`) and turns them into query conditions. Both read the filters from the `X-Proxy-Filter` header, which `auth_request` sets for paths in `lbacPrefixes` (`managed/services/grafana/auth_server.go`) and which nginx sets on every upstream request from the `auth_request` answer, so a client can't supply its own (`pmm.conf:103-104`).

Both treat a missing header as "no restriction". That can't be told apart from a header lost on the way: a path left out of `lbacPrefixes`, or a hop that drops it.

pmm-managed's own APIs, and Grafana's alerting API, apply no Access Role filter. MCP needs three such sources: the inventory (ADR-08), Advisor results (ADR-18) and alerts (ADR-17). ADR-03 keeps authorization out of MCP.

## Options

1. Each MCP tool narrows its own results. This breaks ADR-03, and every other caller of these APIs stays unscoped.
2. Each API applies the filters with its own code.
3. One matcher in pmm-managed, used by every service-scoped API, with the same selectors as for metrics and QAN.

## Decision

Option 3.

**Plumbing, fail-closed.**
- The paths are added to `lbacPrefixes`, so `auth_request` computes the filters for them. pmm-managed's gRPC gateway forwards `X-Proxy-Filter` into gRPC metadata; it has no header matcher today, so one is added [I].
- For these paths, `auth_request` always sets the header: the caller's selectors, or an explicit empty list when the caller is unrestricted (Access Control off, or one of the caller's roles has no filter). Unrestricted is a value, never the absence of one.
- The matcher refuses a request whose header is missing or can't be decoded, with `PermissionDenied`, and logs the path at error level. A route that lost its filter returns nothing instead of everything.
- vmproxy and qan-api2 keep today's behaviour; the explicit empty list is sent only on pmm-managed's service-scoped paths.

**Meaning.**
- Each filter is a series selector, parsed as qan-api2 parses it. An item is visible when its label set matches at least one of the caller's selectors. A selector that can't be parsed refuses the request.
- **A selector matches an item only if the item carries every label the selector names**, and every matcher holds on it. For `=` and for `=~` with a regex that can't match the empty string, this is PromQL's behaviour. For `!=`, `!~`, and `=~` with a regex that matches the empty string, it is stricter than PromQL: an item without the label doesn't match. So `{service_name!="production"}` doesn't match an alert that has no `service_name`.
- **Label set of an item:**
  - a service: its labels (`UnifiedLabels` in `managed/models/service_model.go`) plus its node's;
  - a node: its own labels; a node that hosts a visible service is visible too;
  - an Advisor result: the labels of its service;
  - an alert: its own labels. An alert has one label set, so it belongs to one service at most; text in its annotations that names other services is not used for matching.
- **Counts and summaries** cover visible items only.

## Consequences

- A filter selects the same services for metrics, QAN, the inventory, Advisors and alerts. The meanings differ only for items without a label the filter names: VictoriaMetrics keeps PromQL's behaviour, so a node series without `service_name` still matches `{service_name!="a"}` there, while this matcher hides an alert or a node without it.
- An item that lacks a label the caller's filter names is hidden from that caller, whatever the operator. Server-level alerts, and alerts whose rule aggregates the service labels away, are hidden from every restricted caller. Showing them would need an explicit policy, outside this epic.
- A misconfigured route fails visibly instead of leaking.
- MCP still authorizes nothing (ADR-03); any other caller of these APIs, the PMM UI included, gets the same scoping.
- PMM-wide change: an Editor with a restricted role sees only their services' Advisor results in the UI too.
- Every new service-scoped read API joins `lbacPrefixes` and uses the matcher.
- **Tests:**
  - the matcher against qan-api2's selector cases, plus negative matchers and regexes that match the empty string on items with and without the label;
  - the header removed at each hop: the gRPC handler without metadata, the gateway without the header, and a call to pmm-managed that skips nginx; each refuses;
  - a unit test that lists the gateway's routes for these services and fails when one is not covered by `lbacPrefixes`;
  - the Access Control matrix (spec §11).
