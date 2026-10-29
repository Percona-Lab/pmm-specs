# ADR-15: Metrics tools

- Status: Proposed
- Date: 2026-10-24, revised 2026-10-26
- Tickets: PMM-14247, PMM-15790
- Implemented: not yet (phase 2b)

## Context

Triage needs metrics beyond configuration: load, connections, replication lag, disk, CPU. Today MCP reads metrics only inside `pmm_get_config` and the version lookup in `pmm_inventory`, with instant queries. A model can't ask its own questions.

Four things make free-form metrics costly:
- **Size.** A range query over many series returns tens of thousands of points, and every series repeats its labels. One response can fill a client's context.
- **Work.** Capping the response doesn't cap what VictoriaMetrics does to produce it. A query such as `{__name__=~".+"}` over a long range makes it find and read many series before MCP sees any. PMM's VictoriaMetrics allows 100,000,000 unique series and 1,500,000,000 samples per query, for 90 s (`managed/services/supervisord/supervisord.go:50-55`) [V]. Those limits protect against runaway dashboards, not a model in a loop, and tightening them would hit dashboards too. PMM is the monitoring system; an investigation must not degrade it.
- **Names.** Models don't know PMM's metric names, which differ by engine and exporter version, nor which metrics are counters. A triage turns into guess, empty result, list, retry, and every round trip costs context.
- **Language.** PMM runs VictoriaMetrics' MetricsQL, which differs from PromQL in places.

Each MCP session starts with no memory of the last one.

## Options

1. Built-in queries only: a fixed set of signals per engine.
2. Free-form queries and discovery only.
3. Both, with a catalog of PMM's metrics, a bound on the work each query asks for, and a size budget on every response.

## Decision

Option 3. All metric reads go through the Grafana datasource proxy (ADR-09); vmproxy applies Access Roles to `query`, `query_range`, `series`, `labels` and label values (`vmproxy/proxy/proxy.go:46-50`).

**Tools**
- **`pmm_service_health(service_id, range)`** returns 10 to 15 key signals of one service: load (QPS), threads or connections, replication lag, CPU, memory, disk latency, and engine-specific ones such as the buffer pool hit ratio. The queries are a fixed map in Go, taken from PMM's dashboards and checked against fixtures. One call replaces the usual guessing.
  - Each signal reports its value summary, the time of its last sample, its source (the metric it reads) and a state: `ok` (recent data), `stale` (last sample older than three scrape intervals) or `no_data` (no series). There is no overall healthy or unhealthy verdict.
  - Scrape health keeps three cases apart: `up` is 1, `up` is 0, and `up` is absent or stale.
  - CPU, memory and disk come from the node's series, which carry node labels only. A role that filters on service labels hides them, so they report `no_data`; the tool can't tell that from a node that sends nothing, and says so.
- **`pmm_catalog(kind: metrics, engine)`** returns the curated catalog for MySQL, PostgreSQL, MongoDB or the node: about 30 to 60 metrics each, with name, meaning, unit, counter or gauge, key labels and a ready query. It is hand-curated from the dashboards' queries and kept in step with the exporters by a CI test against their `/metrics` output. ADR-11 serves the QAN column catalogue from the same tool.
- **Live metadata is a possible supplement, not the source.** vmproxy forwards `/api/v1/metadata` (`vmproxy/proxy/proxy.go:51`) [V], and VictoriaMetrics serves it, on by default from v1.137.0; PMM ships v1.154.0 (`build/scripts/vars:58`) [V for the version, I for the default]. But it carries only type, help and unit; it is empty unless each client's vmagent sends metadata [I]; and metadata is kept per metric name, not per series, so Access Roles can't filter it [I]. This epic doesn't call it. Using it later needs those three checked first.
- **`pmm_query_metrics`** runs any instant or range query: the escape hatch for what the built-in signals don't cover.
- **`pmm_list_metrics`** discovers what exists on this server, custom queries included:
  - `search` takes a substring of the metric name, such as `mysql`, `mongodb` or `replication`. The server escapes it (`regexp.QuoteMeta`) and turns it into a `match[]` selector on the label-values endpoint, so `.*` in a search is matched literally and the model writes no regex.
  - `service_id` or `service_name` keeps only the metrics that exist for that service.
  - Label names and values, and the series of a selector, help narrow a query.
  - It looks back 1 h by default. When more names match than the limit, the result groups them by prefix, such as `mysql_global_status_*`, with a count each, so the model can narrow the search. Names that are in the catalog carry its one-line meaning and type.
  - VictoriaMetrics applies the caller's filters on the label endpoints unless `-search.ignoreExtraFiltersAtLabelsAPI` is set; PMM doesn't set it [V]. A test with a restricted role pins this.

**Execution budget**, checked before a query is sent (starting values in spec §8):
- **Selectors name a metric.** Every series selector in the expression names a metric, with `=` or with a `=~` regex that starts with a literal prefix of at least three characters. Anything else, `{__name__=~".+"}` included, answers `invalid_input` with a hint. The expression is parsed with `github.com/VictoriaMetrics/metricsql` (Apache-2.0), a new dependency: the Prometheus parser already in `go.mod` rejects MetricsQL-only syntax.
- **Range** is capped (7 days), and the **step** is at least the range divided by the point budget, so VictoriaMetrics computes a bounded number of points per series.
- **Timeout.** Every query carries VictoriaMetrics' `timeout` argument, which can only lower `-search.maxQueryDuration` [I, VictoriaMetrics docs].
- **Concurrency.** At most 4 metric queries in flight per caller and 8 per pmm-managed replica across all callers; a further call answers `rate_limited` (ADR-05).

**Response budget** for `pmm_query_metrics` (starting values in spec §8):
- One budget per response, in points and bytes, rather than separate caps per series.
- Range results are summarized per series by default (min, avg, max, last); raw points only when the whole result fits.
- A wide result returns the top N series by max value, plus the count of the rest.
- Rows leave out labels that are the same on every series and PMM's internal labels (`agent_id`, `agent_type`, `node_id`, `machine_id`, `instance`, `job`); the shared labels appear once, in a header.

**Steering.** This is advisory; the budgets are the backstop.
- `Instructions` (ADR-11) gain a short metrics block: start with `pmm_service_health`; read the catalog before writing a query; aggregate first (`sum by (service_name)`, `topk`); filter by `service_name` or `service_id`; instant queries for "now", range queries for trends; the language is MetricsQL.
- The `pmm_query_metrics` description repeats the aggregation rule, with one example.
- A summarized or cut result says so, and suggests a narrower query built from the caller's expression, such as `topk(10, <expr>)` or `sum by (service_name) (<expr>)`.

## Consequences

- The common triage costs one call, the catalog one call per engine per session, and free-form queries stay available.
- No metrics response exceeds the budget, whatever the query, and no query reaches VictoriaMetrics without a metric name, a bounded range and a timeout.
- Some valid queries are refused: a selector without a metric name, or a range over 7 days. Dashboards stay the tool for those.
- One new Go dependency, `metricsql`, for parsing.
- The load an agent can put on VictoriaMetrics is measured, not assumed: the acceptance test (spec §7.5) records VictoriaMetrics' CPU, memory and dashboard query latency under broad queries from several callers.
- The built-in signals and the catalog must follow exporter renames; the fixture tests catch drift.
- Steering works only if the client passes `Instructions` to the model. The client matrix (spec §11) checks it.
- Remembering the catalog across sessions is the client's job.
- Label values are returned as stored (ADR-07).
