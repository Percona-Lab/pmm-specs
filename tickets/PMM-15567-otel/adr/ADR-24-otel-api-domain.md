# ADR-24: One API domain for OpenTelemetry management

- Status: Proposed. This changes the paths in PMM-15574 (`/v1/server/log-parser-presets`) and PMM-15571 (`/v1/server/otel:purge`).
- Date: 2026-11-05
- Tickets: PMM-15567, PMM-15571, PMM-15574

## Context

- The tickets put parser presets and purge under `/v1/server`.
- Log sources, log discovery and collector status also need a home, and none of them is a server setting.
- PMM's auth rules are matched per path prefix (`managed/services/grafana/auth_server.go`), so every prefix needs its own rule.
- Reading logs has a different audience: it is Admin-only now, and opens to other roles once LBAC covers it (ADR-18).

## Options

1. The tickets' paths: presets and purge under `/v1/server/...`, and the rest wherever it fits.
2. One domain, `api/otel/v1` with `OtelService`, under `/v1/otel`.
3. One service per resource: presets, sources and status each in their own domain.

## Decision

Option 2:
- `OtelService` under `/v1/otel` holds presets, log sources, discovery, status, purge and, later, the traces receiver.
- One rule: `"/v1/otel": admin`.
- Settings stay in `/v1/server/settings`, as `Settings.otel`.
- Reading logs is a separate domain, `api/logs/v1` with `LogsService` under `/v1/logs`, because its rule changes when LBAC arrives (ADR-18, ADR-23).

## Consequences

- One auth rule covers all OTEL management, so no RPC falls back to the `grafanaAdmin` rule by accident.
- The paths in PMM-15574 and PMM-15571 change.
- The prototype (percona/pmm#5118) uses the old paths; nothing from it is kept as an API.
