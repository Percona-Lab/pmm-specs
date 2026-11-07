# ADR-15: Metrics tools

- Status: Accepted (2026-11-05), after the review in pmm-specs#4
- Date: 2026-10-24, revised 2026-10-26, 2026-10-30, 2026-11-02 and 2026-11-06
- Tickets: PMM-14247, PMM-15790
- Implemented: not yet (plan 05)

## Context

Triage needs metrics beyond configuration: load, connections, replication lag, disk, CPU. Today MCP reads metrics only inside `pmm_get_config` and the version lookup in `pmm_inventory`, with instant queries. A model can't ask its own questions.

Four things make free-form metrics costly:
- **Size.** A range query over many series returns tens of thousands of points, and every series repeats its labels. One response can fill a client's context.
- **Work.** Capping the response doesn't cap what VictoriaMetrics does to produce it. A query such as `{__name__=~".+"}` over a long range makes it find and read many series before MCP sees any. PMM's VictoriaMetrics allows 100,000,000 unique series and 1,500,000,000 samples per query, for 90 s (`managed/services/supervisord/supervisord.go:50-55`) [V]. Those limits protect against runaway dashboards, not a model in a loop, and tightening them would hit dashboards too. PMM is the monitoring system; an investigation must not degrade it.
- **Names.** Models don't know PMM's metric names, which differ by engine and exporter version, nor which metrics are counters. A triage turns into guess, empty result, list, retry, and every round trip costs context.
- **Language.** PMM runs VictoriaMetrics' MetricsQL, which differs from PromQL in places.

Each client conversation starts with no memory of the last one.

## Options

1. Built-in queries only: a fixed set of signals per engine. Rejected: a triage often needs a metric the fixed set lacks.
2. Free-form queries and discovery only. Rejected: every triage starts with guessing names, and nothing bounds the work.
3. Both, with a catalog of PMM's metrics, a bound on the work each query asks for, and a size budget on every response.

## Decision

Option 3. All metric reads go through the Grafana datasource proxy (ADR-09); vmproxy applies Access Roles to `query`, `query_range`, `series`, `labels` and label values (`vmproxy/proxy/proxy.go:46-50`).

**Tools**
- **`pmm_service_health(service_id, period_from, period_to)`** returns the signals a triage starts with, for one service: load (QPS), threads or connections, replication lag, CPU, memory, disk latency, and engine-specific ones such as the buffer pool hit ratio. The queries are a fixed map in Go, taken from PMM's dashboards and checked against fixtures.
  - Each signal reports its value summary, the time of its newest sample (`last_at`) and its source (the metric it reads), or `no_data` when there is no series. MCP derives no "stale" state and no overall verdict: the model compares `last_at` with the window. A signal whose query fails is reported with its error code, and the result is marked `partial` (ADR-11).
  - CPU, memory and disk come from the node's series, which carry node labels only. A role that filters on service labels hides them, so they report `no_data`; the tool can't tell that from a node that sends nothing, and says so.
- **`pmm_catalog(kind: metrics, engine)`** returns the curated catalog for MySQL, PostgreSQL, MongoDB or the node: about 30 to 60 metrics each, with name, meaning, unit, counter or gauge, key labels and a ready query. It is hand-curated from the dashboards' queries and kept in step with the exporters by a CI test against their `/metrics` output. ADR-11 serves the QAN column catalogue from the same tool.
- **Live metadata is a possible supplement, not the source.** vmproxy forwards `/api/v1/metadata` (`vmproxy/proxy/proxy.go:51`) [V], and VictoriaMetrics serves it, on by default from v1.137.0; PMM ships v1.154.0 (`build/scripts/vars:58`) [V for the version, I for the default]. But it carries only type, help and unit; it is empty unless each client's vmagent sends metadata [I]; and metadata is kept per metric name, not per series, so Access Roles can't filter it [I]. This epic doesn't call it. Using it later needs those three checked first.
- **`pmm_query_metrics`** runs any instant or range query, for questions the built-in signals don't cover.
- **`pmm_list_metrics`** discovers what exists on this server, custom queries included:
  - `kind` picks what it lists: metric names, label names, the values of one label, or the series of a selector.
  - `search` takes a substring of the metric name, such as `mysql`, `mongodb` or `replication`. The server escapes it for a regex and for a quoted MetricsQL string and turns it into a `match[]` selector on the label-values endpoint, so `.*` in a search is matched literally and the model writes no regex. This name search is the one selector the execution budget's rules don't cover: it reads metric names only, from the label-values endpoint, with a `limit` and the look-back below.
  - `service_id` or `service_name` keeps only the metrics that exist for that service.
  - Label names and values, and the series of a selector, help narrow a query.
  - Every list request carries VictoriaMetrics' `limit` argument, and a `match[]` selector the caller supplies follows the execution budget's selector rules. The look-back has a default and a cap for every `kind` (spec §8). A label name in the request path is checked against the label-name grammar and escaped. When more names match than the limit, the result groups them by prefix, such as `mysql_global_status_*`, with a count each, so the model can narrow the search. Names that are in the catalog carry its one-line meaning and type.
  - VictoriaMetrics applies the caller's filters on the label endpoints unless `-search.ignoreExtraFiltersAtLabelsAPI` is set; PMM doesn't set it [V]. A test with a restricted role pins this.

**Execution budget**, checked on the parsed expression before a query is sent (values in spec §8). The response budget below bounds what comes back; this bounds what VictoriaMetrics is asked to read. Every refusal answers `invalid_input` with a hint.
- **Parsing.** The expression is parsed with `github.com/VictoriaMetrics/metricsql` (Apache-2.0), a new dependency: the Prometheus parser already in `go.mod` rejects MetricsQL-only syntax. An expression over the length cap or with more series selectors than the cap is refused; PMM's VictoriaMetrics itself accepts 1 MB (`supervisord.go:50`) [V]. Each OR group of a selector's label filters (`{a="x" or b="y"}`) counts as a selector of its own and is checked on its own.
- **Selectors name a metric.** Every series selector names a metric, with `=` or with a `=~` regex that starts with a literal prefix (length in spec §8). A regex name also needs a scope in the same selector: a `service_*` or `node_*` matcher (`service_id`, `service_name`, `node_id`, `node_name`) that is `=`, or `=~` with literal alternatives only (`db1|db2`). `{__name__=~"mysql_.*"}` alone selects a whole engine on every service and is refused, and `service_name=~".+"` is not a scope. `{__name__=~".+"}` and selectors without a metric name are refused.
- **Time read.** The whole span a query reads is capped: the request's range plus the largest lookbehind in the expression. The lookbehind of a path from the root to a selector is the sum of the rollup windows (`[5m]`), subquery ranges (`[30d:5m]`) and `offset`s along it, so nested subqueries add up. A rollup written without a window (`rate(x)`) reads one step back in MetricsQL [I], so it counts one step. So `rate(x[365d])` as an instant query is refused like a 365-day range. The `@` modifier, which moves evaluation to any time, is refused.
- **No templates.** A MetricsQL `WITH` template is refused before parsing: `metricsql` expands it while parsing, so the checks would see only its expansion.
- **Step** is at least the range divided by the point budget, so VictoriaMetrics computes a bounded number of points per series. A subquery's step is at least the span read divided by the point budget, for the same reason.
- **Series selected.** Before a `pmm_query_metrics` query runs, each selector is counted over the span read with the `series` endpoint and a `limit` one above the cap (spec §8). A selector over the cap refuses the query, with a hint to narrow it by service or node and to aggregate.
- **Bounded reads.** MCP reads at most a fixed number of bytes of any VictoriaMetrics response (spec §8), so a result is never decoded whole before the response budget applies.
- **Request.** MCP builds the VictoriaMetrics request from a fixed set of arguments (`query`, `time` or `start`, `end` and `step`, and `timeout`) and passes nothing else through, so no extra argument changes what the checks assumed.
- **Timeout.** Every query carries VictoriaMetrics' `timeout` argument, which can only lower `-search.maxQueryDuration` [I, VictoriaMetrics docs]. It stops a query only after it has run that long, so it backs up the checks above rather than replacing them.
- **Concurrency.** A cap on metric calls in flight per caller and per pmm-managed replica across all callers; a further call answers `rate_limited` (ADR-05). The QAN tools share it, with a capped window.
- **Requests to VictoriaMetrics.** One per-replica limit covers every request MCP sends to VictoriaMetrics, from any tool: each `pmm_service_health` query, the caller's service list (ADR-08) and the list behind alerts (ADR-17) included. It sits below a `-search.maxConcurrentRequests` that PMM sets explicitly, so dashboards and alert evaluation keep slots. A request waits for a slot until its call's deadline.
- **Rate per caller.** A token bucket per caller key limits how often metric calls start, as one does for live calls (ADR-05); an empty bucket answers `rate_limited` with `retry_after` (ADR-11).
- **Fleet size.** The supported fleet size is the one the load test passed with, stated in spec §8 and `mcp.md`.

**Response budget** for `pmm_query_metrics` (values in spec §8):
- One budget per response, in points and bytes, rather than separate caps per series. The byte budget covers the text and the structured content together.
- Range results are summarized per series by default (min, avg, max, last); raw points only when the whole result fits.
- A wide result returns the top N series by max value, plus the count of the rest. A summary that still exceeds the budget returns fewer series.
- NaN and infinite values are returned as `null` with a note, since JSON can't carry them.
- Rows leave out labels that are the same on every series and PMM's internal labels (`agent_id`, `agent_type`, `node_id`, `machine_id`, `instance`, `job`); the shared labels appear once, in a header.

**Steering.** This is advisory; the budgets enforce the limits.
- `Instructions` (ADR-11) gain a short metrics block: start with `pmm_service_health`; read the catalog before writing a query; aggregate first (`sum by (service_name)`, `topk`); filter by `service_name` or `service_id`; instant queries for "now", range queries for trends; the language is MetricsQL.
- The `pmm_query_metrics` description repeats the aggregation rule, with one example.
- A summarized or cut result says so, and suggests a narrower query built from the caller's expression, such as `topk(10, <expr>)` or `sum by (service_name) (<expr>)`.

## Consequences

- The common triage costs one call, the catalog one call per engine per conversation, and free-form queries stay available.
- No metrics response exceeds the budget, whatever the query. No query reaches VictoriaMetrics without a metric name, a literal `service_*` or `node_*` matcher for a regex name, a capped span of time read, a capped length and a timeout. What VictoriaMetrics reads still grows with the number of series selected, up to the cap per selector; the per-replica limits bound how many such reads run at once, and the load test measures them.
- Some valid queries are refused: a selector without a metric name, a regex name without a literal service or node scope, a span over the cap, the `@` modifier, `WITH` templates, fine-stepped subqueries, selectors that match too many series, and long expressions. Dashboards stay the tool for those.
- One new Go dependency, `metricsql`, for parsing.
- The load an AI client can put on VictoriaMetrics is measured, not assumed: the acceptance test (spec §7.4) records VictoriaMetrics' CPU, memory, dashboard query latency and alert-evaluation failures under broad accepted queries and health checks from several callers, on the smallest supported server size, and passes only within a fixed threshold.
- The built-in signals and the catalog must follow exporter renames; the fixture tests catch drift.
- Steering works only if the client passes `Instructions` to the model. The client matrix (spec §11) checks it.
- Remembering the catalog across conversations is the client's job.
- Label values are returned as stored (ADR-07).
