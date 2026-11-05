# ADR-23: Logs are read through the PMM explorer only

- Status: Proposed. Supersedes ADR-07 once accepted.
- Date: 2026-11-05
- Tickets: PMM-15567, PMM-15576, PMM-15722

## Context

- ADR-07 makes logs Admin-only by reading them through a Grafana ClickHouse datasource (uid `pmm-otel`), guarded by a plugin-client middleware in Percona's Grafana fork.
- ADR-21 adds a native explorer in the PMM UI, on a `LogsService` API that builds the SQL itself. Until now both read paths were planned.
- Keeping both has a cost:
  - the fork middleware needs a matching change in every Grafana release (ADR-07, Consequences);
  - a datasource takes raw SQL, so it can never carry LBAC (ADR-18), and would stay Admin-only for good;
  - two log UIs to build, test and document in the same Technical Preview.

## Options

1. Both, as ADR-07 and ADR-21 say: the Grafana datasource and Logs dashboard, plus the native explorer.
2. The native explorer only.
3. Grafana only, with the explorer later.

## Decision

Option 2.

**Kept from ADR-07:**
- Reading logs is Admin-only until ADR-18 is implemented. The rule is `"/v1/logs": admin`.
- The ClickHouse user `otel_reader` has `SELECT` on `otel.*` only. `LogsService` in pmm-managed reads as that user.
- The server collector redacts bearer and `glsa_` tokens, `Authorization` headers and `password=` values before storage.

**Removed:**
- the `pmm-otel` Grafana datasource;
- the Admin-only middleware in the Grafana fork;
- the Grafana Logs dashboard and its Admin-only folder.

**Links:** service dashboards and Inventory link into the explorer.

## Consequences

- No Grafana fork change is needed for logs in each release.
- One read path, the one where LBAC (ADR-18) is later enforced.
- Admins can no longer run ad-hoc SQL over logs from Grafana Explore.
- The explorer is the only log UI, so it is on the 3.12.0 critical path (D25).
- The planned Grafana traces dashboard (PMM-15580) also loses its datasource; traces need a native view, decided when plan 05 is re-planned.
- PMM-15576 is re-scoped to the links into the explorer, or closed, once this ADR is accepted.
