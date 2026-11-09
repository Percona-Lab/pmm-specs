# ADR-18: LBAC for logs and traces

- Status: Proposed
- Date: 2026-10-10
- Tickets: PMM-15567 (follow-up epic to be created)

## Context

PMM's label-based access control (LBAC) stores each role as a PromQL series selector:
- matchers inside a role are ANDed, and a user's roles are ORed;
- a role with an empty filter means full access.

For paths it covers, the nginx auth subrequest passes the user's selectors downstream in `X-Proxy-Filter`. vmproxy applies them to VictoriaMetrics, and qan-api2 turns them into SQL, using labels that pmm-managed copies into each QAN row at ingest.

Logs and traces carry only identity IDs (ADR-02). The labels roles match on live in PostgreSQL. ADR-07 makes logs Admin-only until this ADR is implemented.

## Options

1. **A PMM query API.** It turns the user's selectors into an allow-list of service and node IDs from inventory, and binds that list as SQL parameters.
2. **Stamp LBAC labels onto records at ingest,** then translate selectors into SQL over them, as QAN does.
3. **ClickHouse row policies,** one per PMM role.
4. **A SQL-rewriting proxy** in front of ClickHouse, or Grafana-side controls only.

## Decision

Option 1, with node identity verified at ingest.

1. **Ingest.**
   - For a per-node service-account token, the auth server returns the node's id in a response header, and nginx passes it to the server collector.
   - The collector overwrites `pmm.node_id` from it.
   - Records sent with shared credentials are marked `pmm.identity_verified=false`.
2. **Query.** `/v1/logs:search` and `/v1/traces:search` take structured filters only: time, node, service, app, severity and text. Both are LBAC-covered paths.
3. **Resolution.**
   - Selectors are evaluated with Prometheus matcher semantics (anchored regexes; a missing label equals `""`).
   - They are evaluated against `MergeLabels(node, service)` for each service, and `MergeLabels(node)` for each node.
   - The resulting predicate is `(PmmServiceId, PmmNodeId) IN {allowed pairs} OR (PmmServiceId = '' AND PmmNodeId IN {allowed nodes})`.
   - For restricted users it also requires `pmm.identity_verified=true`. Records without it, including everything stored before ingest verification ships, are visible to Admins only.
4. **Fail closed.**
   - While access control is disabled (the default, `AccessControlEnabledDefault = false`), `/v1/logs` and `/v1/traces` stay Admin-only (ADR-23). Non-Admins reach them only when access control is enabled.
   - `/v1/logs` and `/v1/traces` are LBAC-covered paths, so a restricted user's request always carries the user's selectors.
   - With access control enabled, a request without the header is full access: the auth server sends none when the user has no filters.
   - Any selector that doesn't parse means deny.
   - Service-account and anonymous credentials, which skip LBAC today, follow an explicit rule (plan 07, Task 3) before these paths open to non-Admins.
5. **Defaults.** A PMM UI log explorer uses the API. There is no Grafana OTEL datasource (ADR-23).

Options 2–4 were rejected for these reasons:
- Labels stamped at ingest freeze access at write time.
- Row policies need per-request identity in ClickHouse, and sync on every role and inventory change.
- Any divergence between a rewriting proxy's SQL parser and ClickHouse's is a bypass.
- Grafana-side controls are not a security boundary.

## Consequences

- **Access follows current labels:**
  - revoking a role hides old logs at once;
  - logs of a deleted service become invisible to restricted users;
  - node-level logs need node labels, as node metrics do today.
- **Partial traces.** A trace that crosses services returns only the spans the user may see, and is marked partial.
- **Shared code.** The selector evaluator is shared code that other LBAC consumers can adopt.
- **Records stored before ingest verification** carry no `pmm.identity_verified`, so they stay Admin-only and need no migration.
- **Spoofed rows.** The pair predicate means a record claiming another node's service never matches that service.
