# ADR-15: Metrics tools

- Status: Proposed
- Date: 2026-10-24
- Tickets: PMM-14247, PMM-15790
- Implemented: not yet (phase 2b)

## Context

Triage needs metrics beyond configuration: load, connections, replication lag, disk, CPU. Today MCP reads metrics only inside `pmm_get_config` and the version lookup in `pmm_inventory`, with instant queries. A model can't ask its own questions. PromQL written by a model can be expensive, and range results can be large.

## Options

1. Fixed tools per question: replication lag, connections, and so on.
2. One query tool plus metric discovery.
3. Both.

## Decision

Option 2, through the Grafana datasource proxy (ADR-09). vmproxy applies Access Roles to `query`, `query_range`, `series`, `labels` and label values (`vmproxy/proxy/proxy.go:46-50`), so both tools are scoped like dashboards.
- **`pmm_query_metrics`** runs an instant or a range query. A range result is summarized per series by default (min, avg, max, last); raw points come only on request, downsampled to the point cap.
- **`pmm_list_metrics`** lists metric names matching a pattern, label names, label values, and the series of a selector, within a time range.
- **Caps** on series per result, points per series, range length, a step floor, and a query timeout passed to VictoriaMetrics. Starting values are in spec §8.
- **Per caller,** at most 4 metric queries in flight; a further call answers `rate_limited` (ADR-05).
- **`pmm_get_config`** stays, as a shortcut for configuration variables.
- **`Instructions`** say the language is VictoriaMetrics' MetricsQL, and send the model to `pmm_list_metrics` for names rather than carrying a catalogue.

## Consequences

- Any question a PMM dashboard answers, the model can ask, scoped as the dashboard is.
- Model-written queries load PMM's own VictoriaMetrics. The caps, the per-caller limit and VictoriaMetrics' search limits bound that load.
- MetricsQL and PromQL differ in places, so a model that assumes PromQL can misread a result.
- Label values are returned as stored (ADR-07).
