# ADR-15: Metrics tools

- Status: Proposed
- Date: 2026-10-24
- Tickets: PMM-14247, PMM-15790
- Implemented: not yet (phase 2b)

## Context

Triage needs metrics beyond configuration: load, connections, replication lag, disk, CPU. Today MCP reads metrics only inside `pmm_get_config` and the version lookup in `pmm_inventory`, with instant queries. A model can't ask its own questions.

Three things make free-form metrics costly for a model:
- **Size.** A range query over many series returns tens of thousands of points, and every series repeats its labels. One response can fill a client's context.
- **Names.** Models don't know PMM's metric names, which differ by engine and exporter version, nor which metrics are counters. A triage turns into guess, empty result, list, retry, and every round trip costs context.
- **Language.** PMM runs VictoriaMetrics' MetricsQL, which differs from PromQL in places.

Each MCP session starts with no memory of the last one.

## Options

1. Built-in queries only: a fixed set of signals per engine.
2. Free-form queries and discovery only.
3. Both, with a catalog of PMM's metrics and a size budget on every response.

## Decision

Option 3. All metric reads go through the Grafana datasource proxy (ADR-09); vmproxy applies Access Roles to `query`, `query_range`, `series`, `labels` and label values (`vmproxy/proxy/proxy.go:46-50`).

**Tools**
- **`pmm_service_health(service_id, range)`** returns 10 to 15 key signals of one service, already summarized: load (QPS), threads or connections, replication lag, CPU, memory, disk latency, and engine-specific ones such as the buffer pool hit ratio. The queries are a fixed map in Go, taken from PMM's dashboards and checked against fixtures. One call replaces the usual guessing.
- **`pmm_catalog(kind: metrics, engine)`** returns the curated catalog for MySQL, PostgreSQL, MongoDB or the node: about 30 to 60 metrics each, with name, meaning, unit, counter or gauge, key labels and a ready query. It is hand-curated from the dashboards' queries and kept in step with the exporters by a CI test against their `/metrics` output. ADR-11 serves the QAN column catalogue from the same tool. Live metadata is not an option: vmproxy doesn't forward the metadata endpoint.
- **`pmm_query_metrics`** runs any instant or range query: the escape hatch for what the built-in signals don't cover.
- **`pmm_list_metrics`** discovers what exists on this server: metric names matching a pattern, label names and values, the series of a selector. It covers custom queries.

**Response budget** for `pmm_query_metrics` (starting values in spec §8):
- One budget per response, in points and bytes, rather than separate caps per series.
- Range results are summarized per series by default (min, avg, max, last); raw points only when the whole result fits.
- The step is chosen from the range and the point budget, unless the caller sets one.
- A wide result returns the top N series by max value, plus the count of the rest.
- Rows leave out labels that are the same on every series and PMM's internal labels (`agent_id`, `agent_type`, `node_id`, `machine_id`, `instance`, `job`); the shared labels appear once, in a header.
- Per caller, at most 4 metric queries in flight; a further call answers `rate_limited` (ADR-05). Each query carries a timeout to VictoriaMetrics.

**Steering.** This is advisory; the budget is the backstop.
- `Instructions` (ADR-11) gain a short metrics block: start with `pmm_service_health`; read the catalog before writing a query; aggregate first (`sum by (service_name)`, `topk`); filter by `service_name` or `service_id`; instant queries for "now", range queries for trends; the language is MetricsQL.
- The `pmm_query_metrics` description repeats the aggregation rule, with one example.
- A summarized or cut result says so, and suggests a narrower query built from the caller's expression, such as `topk(10, <expr>)` or `sum by (service_name) (<expr>)`.

## Consequences

- The common triage costs one call, the catalog one call per engine per session, and free-form queries stay available.
- No metrics response exceeds the budget, whatever the query.
- The built-in signals and the catalog must follow exporter renames; the fixture tests catch drift.
- Model-written queries still load PMM's VictoriaMetrics; the per-caller limit, the timeout and VictoriaMetrics' search limits bound that load.
- Steering works only if the client passes `Instructions` to the model. The client matrix (spec §11) checks it.
- Remembering the catalog across sessions is the client's job.
- Label values are returned as stored (ADR-07).
