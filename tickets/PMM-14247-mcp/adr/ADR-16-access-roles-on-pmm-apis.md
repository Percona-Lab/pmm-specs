# ADR-16: Access Roles on PMM's service-scoped APIs

- Status: Deferred (2026-11-02): out of the MCP epic, to a PMM ticket not yet filed, whose work lands on `main`
- Date: 2026-10-24, revised 2026-10-26, 2026-10-30 and 2026-11-02
- Tickets: PMM-14247, PMM-15531, PMM-15536
- Implemented: not planned in this epic

## Deferred

MCP no longer depends on this record. Its service list comes from Access-Role-filtered series (ADR-08), and it narrows alerts and Advisor results to that list itself (ADR-03, ADR-17, ADR-18). Applying Access Roles to pmm-managed's own APIs and to Grafana's alerts is PMM-wide work, so it moves to its own ticket on `main`, outside this epic. The design below is kept as input for that ticket, which re-decides it; it predates the 2026-11-02 revisions of ADR-03 and ADR-08, and where they differ, those records govern. MCP's narrowing (ADR-03) is the interim answer for MCP's own results. Before it is accepted there, it also settles:
- every gateway in front of an Access-Role-filtered API takes the filter from exactly one path and refuses a request that carries more than one value;
- the exact encoding of "unrestricted", since nginx sends no header for an empty value;
- the matching semantics, defined and tested on their own rather than copied from another component;
- the full list of nginx locations that change, and the ones excluded;
- what anonymous callers get.

## Context

Access Roles filter two sources today. Metrics: vmproxy injects the caller's filters as `extra_filters[]` into VictoriaMetrics queries. QAN: qan-api2 parses them with Prometheus's selector parser (`qan-api2/models/reporter.go:808`) and turns them into query conditions. Both read the filters from the `X-Proxy-Filter` header, which `auth_request` sets for paths in `lbacPrefixes` (`managed/services/grafana/auth_server.go`).

nginx sets that header per location; the locations in front of pmm-managed's own APIs don't set it, and nothing in pmm-managed reads it today [V].

pmm-managed's inventory and Advisor APIs, and Grafana's alerting API, apply no Access Role filter. MCP needs three such sources: the inventory (ADR-08), Advisor results (ADR-18) and alerts (ADR-17). ADR-03 keeps authorization out of MCP.

## Options

1. Each MCP tool narrows its own results. Rejected as the PMM-wide answer: every other caller of these APIs stays unfiltered. (It is what MCP does in the meantime, ADR-03.)
2. Each API applies the filters with its own code. Rejected: several implementations of one rule, which drift.
3. One matcher in pmm-managed, used by every service-scoped API, with the same selectors as for metrics and QAN.

## Decision

Option 3.

**Plumbing: only `auth_request`'s value reaches the matcher.**
- **nginx.** `location /v1/` sets `X-Proxy-Filter` and `X-Proxy-Admin` explicitly with `proxy_set_header`, and the gRPC locations to pmm-managed set them with `grpc_set_header`. A client's own value never reaches pmm-managed.
- **`lbacPrefixes`** gains the REST paths of these APIs and the gRPC method paths that nginx exposes for them (`/inventory.v1.ServicesService/`, `/inventory.v1.NodesService/`), so `auth_request` computes the filters on both routes. The Advisor and alerting services have no gRPC location in nginx.
- **Gateway.** pmm-managed's gRPC gateway forwards `X-Proxy-Filter` into gRPC metadata; it has no header matcher today, so one is added [I].
- **Always a value.** For these paths, `auth_request` always sets the header: the caller's selectors, or an explicit empty list when the caller is unrestricted (Access Control off, one of the caller's roles has no filter, or the caller is Admin, below). Unrestricted is a value, never the absence of one.
- **Matcher.** It accepts exactly one `x-proxy-filter` value. A request with none, more than one, or one that can't be decoded is refused with `PermissionDenied`, and the path is logged at error level. A route that lost its filter returns nothing instead of everything.
- The explicit empty list is sent only on pmm-managed's service-scoped paths.

**Admins are not filtered by this matcher.** `auth_request` already knows the caller's role (`auth_server.go:352`) and sends the explicit empty list for an Admin on these paths. Two reasons:
- PMM's own node accounts are Admin service accounts (`CreateServiceAccount`, `managed/services/grafana/client.go:668`). pmm-agent's setup and pmm-admin's `list`, `remove` and `unregister` read the inventory with them. Under ADR-12, a restricted default role would hide the node's own services and node from them, and `pmm-agent setup` would take its own node as unregistered and register it again.
- Access Roles don't bind an Admin, who can change their own roles.

Metrics and QAN keep filtering a restricted Admin, as they do today.

**Meaning.**
- Each filter is a Prometheus series selector. An item is visible when its label set matches at least one of the caller's selectors. A selector that can't be parsed refuses the request.
- **A selector matches an item only if the item carries every label the selector names**, and every matcher holds on it. For `=` and for `=~` with a regex that can't match the empty string, this is PromQL's behaviour. For `!=`, `!~`, and `=~` with a regex that matches the empty string, it is stricter than PromQL: an item without the label doesn't match. So `{service_name!="production"}` doesn't match an alert that has no `service_name`.
- **Label set of an item:**
  - a service: its labels (`UnifiedLabels` in `managed/models/service_model.go`) plus its node's;
  - a node: its own labels; a node that hosts a visible service is visible too;
  - an Advisor result: the labels of its service;
  - an alert: its own labels. An alert has one label set, so it belongs to one service at most; text in its annotations that names other services is not used for matching.
- **Counts and summaries** cover visible items only.

## Consequences

- A filter selects the same services for metrics, QAN, the inventory, Advisors and alerts. The meanings differ only for items without a label the filter names: VictoriaMetrics keeps PromQL's behaviour, so a node series without `service_name` still matches `{service_name!="a"}` there, while this matcher hides an alert or a node without it.
- A restricted Admin sees the full inventory, every alert and every Advisor result, but filtered metrics and QAN.
- An item that lacks a label the caller's filter names is hidden from that caller, whatever the operator. Server-level alerts, and alerts whose rule aggregates the service labels away, are hidden from every restricted caller. Showing them would need an explicit policy, outside this epic.
- A misconfigured route fails visibly instead of leaking, and a client can't choose its own filter.
- nginx changes with this ADR: `/v1/` and the gRPC locations set the headers that the vmproxy and qan-api2 locations already set.
- MCP still authorizes nothing (ADR-03); any other caller of these APIs, the PMM UI included, gets the same scoping.
- PMM-wide change: an Editor with a restricted role sees only their services' Advisor results in the UI too.
- Every new service-scoped read API joins `lbacPrefixes` and uses the matcher.
- **Tests:**
  - the matcher against its own selector cases, including negative matchers and regexes that match the empty string on items with and without the label;
  - a client that sends its own `X-Proxy-Filter`, on the REST and on the gRPC route, gets the filter of its real role; two `X-Proxy-Filter` values are refused;
  - the header removed at each hop: the gRPC handler without metadata, the gateway without the header, and a call to pmm-managed that skips nginx; each refuses;
  - a static test over `pmm.conf`: every location that proxies to pmm-managed, qan-api2 or vmproxy sets `X-Proxy-Filter` and `X-Proxy-Admin` itself;
  - a route-coverage unit test over the gateway routes and the gRPC method names of these services, which fails when one is not covered by `lbacPrefixes`;
  - with a restricted default role, a registered node's own account: `pmm-admin list`, `remove` and `unregister`, and `pmm-agent setup`, work as before;
  - the Access Control matrix (spec §11).
