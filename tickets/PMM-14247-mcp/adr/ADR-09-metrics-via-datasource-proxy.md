# ADR-09: Metrics through the Grafana datasource proxy

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15533
- Implemented: `PMM-MCP-GA`, percona/pmm#5942 (D7 in `DECISIONS.md`)

## Context

`pmm_get_config`, the version and health lookups in `pmm_inventory`, and the metrics tools (ADR-15) read metrics. The raw `/prometheus` path is Admin-only. The path must be readable by a Viewer and must carry LBAC filters.

## Options

1. The raw VictoriaMetrics path.
2. Grafana's datasource proxy by numeric ID.
3. Grafana's datasource proxy by uid, with the uid looked up per call.

## Decision

Option 3. `GET /graph/api/datasources/name/Metrics` returns the uid, with the caller's credentials, on every call; nothing is cached across callers. Queries then go to `/graph/api/datasources/proxy/uid/{uid}/api/v1/query`, and for ADR-15 also to `query_range`, `series`, `labels` and label values under the same prefix, all of which vmproxy filters. LBAC filters apply to that path: #5942 added `/graph/api/datasources/proxy/uid/` to `lbacPrefixes` (PMM-15533), and `main`, merged into `PMM-MCP-GA` since, covers the whole `/graph/api/datasources/` tree.

## Consequences

- Plain Prometheus responses, Viewer-readable, filtered by LBAC for callers that have roles.
- One small extra call per tool call, and no stale cache.
- The tool selects the datasource by name, so renaming PMM's `Metrics` datasource would break it.
