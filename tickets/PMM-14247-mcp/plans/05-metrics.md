# Metrics tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pmm_query_metrics`, `pmm_list_metrics`, `pmm_service_health`, the metrics catalogue in `pmm_catalog`, and scrape health in `pmm_inventory`, each bounded in what it asks VictoriaMetrics to read and in what it returns.

**Architecture:** Every read goes through the Grafana datasource proxy (ADR-09) with a fixed set of arguments. Before a query is sent, `checkExpr` parses it with `metricsql` and enforces the execution budget; after, `shapeSeries` enforces the response budget. Metric calls share plan 02's `limiter` with their own counts.

**Tech Stack:** Go 1.27, go-sdk v1.8.0, `github.com/VictoriaMetrics/metricsql` v0.87.5 (Apache-2.0, new dependency), VictoriaMetrics v1.154.0 behind vmproxy.

**Spec:** [ADR-15](../adr/ADR-15-metrics-tools.md), [spec §7.1, §7.4, §7.5, §8](../spec.md#71-metrics), [ADR-09](../adr/ADR-09-metrics-via-datasource-proxy.md).

## Global Constraints

- Needs plan 02 (`limiter`, `callerKey`, `codeRateLimited`) and plan 03 (`addTool`, `window`, `page`, `pmm_catalog`).
- Execution budget: expression ≤ 4 KiB and ≤ 10 series selectors; every selector names a metric with `=` or a `=~` regex with a literal prefix of ≥ 3 characters, and a regex name also needs a `service_id`, `service_name`, `node_id` or `node_name` matcher in the same selector that is `=`, or `=~` with a regex of literal alternatives only (`db1|db2`), so `=~".+"` doesn't count as a scope; span read = range + largest (rollup window or subquery range) + largest `offset` ≤ 7 days; `@` refused. Every refusal is `invalid_input` with a hint, before any request.
- Request arguments: only `query`, `time` or `start`/`end`/`step`, and `timeout`. Timeout 30 s.
- Response budget: 20 series by default, 100 maximum, top N by max; 2,000 points and 16 KiB per response; summaries (min, avg, max, last) when raw points don't fit; internal labels `agent_id`, `agent_type`, `node_id`, `machine_id`, `instance`, `job` dropped from rows; labels shared by every series shown once.
- Default range 1 h. Step ≥ range / 2,000.
- Concurrency: 4 metric calls per caller, 8 per replica; `pmm_service_health` and `pmm_list_metrics` count as one call each.
- `stale`: last sample older than 3 × the low metrics resolution (`metrics_resolutions.lr` from `GET /v1/server/settings/readonly`, 60 s by default).
- Spec §7.5's load-test example runs a `[5m]` window over 7 days, which reads 7 days and 5 minutes and is refused by the cap; tests here use 6 days.

## Review Focus

- **A model that asks for `rate(x[5m])` over exactly 7 days** gets a refusal that tells it the span and the cap, not a generic error: Task 2 tests the hint text.
- **A result with one huge series and many small ones** keeps the huge one in the top N and says how many were left out: Task 3 tests `total_series` and the hint.
- **VictoriaMetrics answering 422 for a bad expression** must surface as `invalid_input` with VictoriaMetrics' message, not `pmm_unavailable`: Task 1 tests the mapping.
- **Node signals under a service-filtered role** report `no_data` with the note that it can mean "hidden", never `ok` or an error: Task 7 tests it.
- **A catalogue entry whose metric was renamed upstream** fails CI, not at a customer: Task 6's fixture test.

---

### Task 1: Client calls with a fixed argument set

**Files:** Modify `managed/services/mcp/client.go`, `deps.go` (`pmmAPI`), `errors.go` (422), `helpers_test.go` (`fixture.body`); Test `client_test.go` (new).

**Interfaces:**
- Produces:
  - `type promRequest struct { Query string; Time, Start, End time.Time; Step, Timeout time.Duration }` with `func (r promRequest) values() url.Values`: only the non-zero ones of `query`, `time`, `start`, `end`, `step` (seconds), `timeout` (Go duration string).
  - `type point struct { T time.Time \`json:"t"\`; V float64 \`json:"v"\` }`; `type metricSeries struct { Labels map[string]string; Points []point }`.
  - `pmmAPI` gains: `QueryRange(ctx context.Context, auth callerAuth, uid string, r promRequest) ([]metricSeries, error)`; `LabelValues(ctx context.Context, auth callerAuth, uid, label string, match []string, start, end time.Time) ([]string, error)`; `Labels(ctx context.Context, auth callerAuth, uid string, match []string, start, end time.Time) ([]string, error)`; `Series(ctx context.Context, auth callerAuth, uid string, match []string, start, end time.Time) ([]map[string]string, error)`. `QueryInstant` takes `(ctx, auth, uid string, r promRequest)`; its two callers pass `promRequest{Query: …, Time: at}`.
  - `mapError`: HTTP 422 becomes `invalid_input`.
  - `fixture` gains `body []byte`, served instead of `file` when set.

- [ ] **Step 1: Write `TestPromRequestArguments`:** for an instant and a range request, the recorded query string has exactly the expected keys (e.g. `query`, `start`, `end`, `step`, `timeout`) and `timeout=30s`; a zero `Time` sends no `time`. **`TestQueryRangeDecodes`** a matrix fixture into series and points. **`TestMapError422`**.
- [ ] **Step 2: Run, see FAIL; implement; regenerate the `pmmAPI` mock per `.mockery.yaml`; run the package, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Add range, label and series calls to the MCP client`.

### Task 2: Execution budget

**Files:** Create `managed/services/mcp/metrics_check.go`, `metrics_check_test.go`; Modify `go.mod` (`go get github.com/VictoriaMetrics/metricsql@v0.87.5`).

**Interfaces:**
- Produces: `const maxExprBytes = 4096`, `maxSelectors = 10`, `maxSpan = 7 * day`, `minNamePrefix = 3`; `func checkExpr(expr string, span, step time.Duration) error`. Durations use `DurationExpr.Duration(step.Milliseconds())`; `metricsql.VisitAll` walks `*MetricExpr` (`LabelFilterss`) and `*RollupExpr` (`Window`, `Step`, `Offset`, `At`).

- [ ] **Step 1: Write `TestCheckExpr`**, table of `(expr, span, want error substring or "")`:

| expr | span | want |
|---|---|---|
| `rate(mysql_global_status_questions[5m])` | 6d | "" |
| `sum by (service_name) (rate(mysql_global_status_questions{service_name="db1"}[5m]))` | 1h | "" |
| `{__name__=~"mysql_global_status_.*", service_name=~"db1\|db2"}` | 1h | "" |
| `{__name__=~"mysql_global_status_.*", service_name=~".+"}` | 1h | "service_id, service_name, node_id or node_name" |
| `rate(mysql_global_status_questions[7d])` | 0 | "" |
| `rate(mysql_global_status_questions[5m])` | 7d | "7 days" |
| `{__name__=~".+"}` | 1h | "metric name" |
| `{job="mysql"}` | 1h | "metric name" |
| `{__name__!="up"}` | 1h | "metric name" |
| `{__name__=~"mysql_.*"}` | 1h | "service_id, service_name, node_id or node_name" |
| `{__name__=~"my.*", service_name="db1"}` | 1h | "prefix" |
| `rate(mysql_global_status_questions[365d])` | 0 | "7 days" |
| `max_over_time(rate(up[5m])[30d:5m])` | 0 | "7 days" |
| `up offset 8d` | 0 | "7 days" |
| `up @ 1700000000` | 0 | "@" |
| `up @ start()` | 0 | "@" |
| 11 selectors joined by `+` | 1h | "10 selectors" |
| 5,000-byte expression | 1h | "4 KiB" |
| `rate(` | 1h | "parse" |

- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.** `go test ./managed/services/mcp/ -run TestCheckExpr -v`. Confirm `make check-license`/license CI accepts Apache-2.0.
- [ ] **Step 3: Commit** `PMM-15790 Bound what a metrics query may read`.

### Task 3: Response budget

**Files:** Create `managed/services/mcp/metrics_budget.go`, `metrics_budget_test.go`.

**Interfaces:**
- Produces:
  - `const defaultSeries = 20`, `maxSeriesShown = 100`, `maxPoints = 2000`, `maxMetricsBytes = 16 << 10`, `metricsTimeout = 30 * time.Second`, `defaultMetricsRange = time.Hour`.
  - `var internalLabels = []string{"agent_id", "agent_type", "node_id", "machine_id", "instance", "job"}`
  - `func chooseStep(span, requested time.Duration) time.Duration`: `max(requested, ceil(span/maxPoints) to the second, 1s)`; 0 for an instant query.
  - `type seriesSummary struct { Labels map[string]string \`json:"labels"\` (Untrusted); Min, Avg, Max, Last float64; LastAt time.Time \`json:"last_at"\`; Points []point \`json:"points,omitempty"\` }`
  - `type metricsResult struct { Query string; Window *window; Step string; SharedLabels map[string]string (Untrusted); Series []seriesSummary; TotalSeries int; Truncated bool; Summarized bool; Hint string }` (snake_case JSON) with `render()`: a header with the shared labels, one row per series with min, avg, max, last, then the hint.
  - `func shapeSeries(expr string, series []metricSeries, limit int) metricsResult`

- [ ] **Step 1: Write `TestShapeSeries`:** 300 series → 20 kept, ordered by max descending, `total_series` 300, `truncated`, hint contains `topk(10, <expr>)` and `sum by (service_name) (<expr>)`; internal labels absent from every series; a label equal on all series moves to `shared_labels`; 3 series × 50 points keep `points`; 20 series × 200 points (4,000) are `summarized` with no `points`; a result whose points JSON exceeds 16 KiB is summarized. **`TestChooseStep`:** 1h → 2s, 6d → 260s (259.2 s rounded up), requested 5m on 1h → 5m.
- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Shape metrics results to a budget`.

### Task 4: `pmm_query_metrics`

**Files:** Create `managed/services/mcp/tools_metrics.go`, `tools_metrics_test.go`; Modify `mcp.go` (`Service.metrics *limiter`, `newLimiter(4, 8)`; register).

**Interfaces:**
- Produces: `type queryMetricsInput struct { Query string \`json:"query"\`; Time string \`json:"time,omitempty"\`; PeriodFrom string \`json:"period_from,omitempty"\`; PeriodTo string \`json:"period_to,omitempty"\`; Step string \`json:"step,omitempty"\`; Limit int \`json:"limit,omitempty"\` }`. `period_from` makes it a range query (window by `parseWindow`); otherwise instant at `time` (default now). `const maxMetricCallsPerCaller = 4`, `maxMetricCallsPerReplica = 8`.

- [ ] **Step 1: Write `TestQueryMetricsTool`:** an instant and a range call against `body` fixtures (`/graph/api/datasources/name/Metrics`, `.../proxy/uid/<uid>/api/v1/query_range`); a refused expression records no request to the proxy; a 300-series response is cut to 20 with the hint; `limit: 101` is `invalid_input`; with the caller's key at 4 on `s.metrics`, `rate_limited`; 8 other keys, `rate_limited`; the description says "MetricsQL", "aggregate first", and gives one `sum by (service_name)` example.
- [ ] **Step 2: Run, see FAIL; implement (check → limiter → datasource uid → client → `shapeSeries`); run the package, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Add pmm_query_metrics`.

### Task 5: `pmm_list_metrics`

**Files:** Modify `tools_metrics.go`, `tools_metrics_test.go`.

**Interfaces:**
- Produces:
  - `type listMetricsInput struct { Search, ServiceID, ServiceName, Label string; Match []string; PeriodFrom string; Limit int }` (snake_case JSON: `search`, `service_id`, `service_name`, `label`, `match`, `period_from`, `limit`). Mode: `label` → that label's values; `match` → series; otherwise metric names.
  - `func nameSelector(search, serviceID, serviceName string) string`: `{__name__=~".*<regexp.QuoteMeta(search)>.*"}` plus the service matcher.
  - `type nameGroup struct { Prefix string \`json:"prefix"\`; Count int \`json:"count"\` }`; `func groupNames(names []string, limit int) ([]string, []nameGroup)`: over the limit, group by the first three `_`-separated parts (`mysql_global_status_*`); if still over, by the first two.
  - `type listMetricsResult struct { Names []metricName; Groups []nameGroup; Values []string (Untrusted); Series []map[string]string (Untrusted); Page page }`; `type metricName struct { Name, Meaning, Type string }` (meaning and type from the catalogue when present).
- Default look-back 1 h; 100 names or values by default, 1,000 maximum. `match` selectors pass `checkExpr` with the look-back as span.

- [ ] **Step 1: Write `TestListMetricsTool`:** `search: ".*"` sends `match[]={__name__=~".*\.\*.*"}`; `search: mongodb` with `service_name: db1` adds `service_name="db1"`; 1,500 names → groups with counts; a catalogue name carries its meaning; `match: ["{__name__=~\".+\"}"]` is `invalid_input`. **`TestGroupNames`.**
- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Add pmm_list_metrics`.

### Task 6: Metrics catalogue in `pmm_catalog`

**Files:** Create `managed/services/mcp/metrics_catalog.go`, `metrics_catalog_test.go`, `testdata/exporters/{mysql,postgresql,mongodb,node}.prom`; Modify `tools_catalog.go` (`kind: metrics`).

**Interfaces:**
- Produces: `type metricInfo struct { Name, Engine, Meaning, Unit, Type string; Labels []string; Query string }` (`Type`: `counter` or `gauge`; `Query`: a ready MetricsQL expression using `service_name="<service>"`); `var metricsCatalog []metricInfo`, 30 to 60 per engine (`mysql`, `postgresql`, `mongodb`, `node`), taken from the queries of PMM's dashboards in `dashboards/dashboards/`; `func metricInfoByName(name string) (metricInfo, bool)`. `catalogEntry` gains `Meaning`, `Unit`, `Type`, `Labels`, `Query` (omitempty).

- [ ] **Step 1: Capture `/metrics` output** of mysqld_exporter, postgres_exporter, mongodb_exporter and node_exporter from a CHAOS VM running the versions `PMM-MCP-GA` ships; note the versions in the file headers.
- [ ] **Step 2: Write `TestMetricsCatalogMatchesExporters`** (every catalogue name appears in its engine's fixture; `counter` names end in `_total` or are typed `counter` in the fixture's `# TYPE`) and **`TestMetricsCatalogQueriesPass`** (each `Query`, with `<service>` replaced, passes `checkExpr` over 1 h).
- [ ] **Step 3: Run, see FAIL; write the catalogue; run, see PASS.** Extend `TestCatalogQANColumns` with `kind: metrics, engine: postgresql`.
- [ ] **Step 4: Commit** `PMM-15790 Add the metrics catalogue to pmm_catalog`.

### Task 7: `pmm_service_health`

**Files:** Create `managed/services/mcp/tools_health.go`, `tools_health_test.go`, `testdata/health_*.json`; Modify `client.go`/`deps.go` if `GET /v1/server/settings/readonly` is not yet in `pmmAPI` (`ReadOnlySettings`).

**Interfaces:**
- Produces:
  - `type signal struct { Name, Unit, Source, Query string; Node bool }`; `Query` has one `%s` for the selector (`service_name="…"` or, when `Node`, `node_name="…"`). `var healthSignals = map[string][]signal{…}`: 10 to 15 per engine (load as QPS, threads or connections, replication lag, CPU, memory, disk latency, and engine ones such as the buffer pool hit ratio), queries taken from PMM's dashboards.
  - `type signalResult struct { Name, Unit, Source, State string; Min, Avg, Max, Last *float64; LastAt *time.Time }` (`State`: `ok`, `stale`, `no_data`).
  - `type healthResult struct { ServiceID, ServiceName, Engine string; Window window; Scrape scrapeState; Signals []signalResult; Note string; PMMURL string }`.
  - `func signalState(last time.Time, now time.Time, lowResolution time.Duration) string`.
- One call holds one metrics slot and runs its signal queries at most 4 at a time; a failing signal reports `no_data` with its error in `Note`, not a failed call.

- [ ] **Step 1: Write `TestServiceHealthTool`:** a MySQL fixture returns every signal `ok` with min/avg/max/last; a signal whose last sample is 4 minutes old (low resolution 60 s) is `stale`; an empty node signal is `no_data` and `note` says it may be hidden by an Access Role; no field is a healthy/unhealthy verdict; an unknown `service_id` is `not_found`. **`TestSignalState`.** **`TestHealthSignalsPass`:** every query, filled in, passes `checkExpr`.
- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Add pmm_service_health`.

### Task 8: Scrape health in `pmm_inventory`

**Files:** Modify `tools_inventory.go`; Test `tools_inventory_test.go`.

**Interfaces:**
- Produces: `type scrapeState struct { State string \`json:"state"\`; LastAt *time.Time \`json:"last_at,omitempty"\` }` (`up`, `down`, `unknown`); `serviceRow.Scrape scrapeState \`json:"scrape"\``. Two instant queries per call, beside the version query: `max by (service_id) (up{service_id!=""})` and `max by (service_id) (timestamp(up{service_id!=""}))`.

- [ ] **Step 1: Extend `TestInventoryTool`:** `up` 1 → `up`; 0 → `down`; no series or last sample older than 3 × low resolution → `unknown` with `last_at` when known; a failing metrics call leaves `unknown`, not an error.
- [ ] **Step 2: Run, see FAIL; implement; run, see PASS. Commit** `PMM-15790 Report scrape health in pmm_inventory`.

### Task 9: Instructions, docs, live checks and the load test

**Files:** Modify `mcp.go` (`Instructions`), `documentation/docs/api/mcp.md`; Test `mcp_test.go`, `api-tests/mcp/mcp_test.go`.

- [ ] **Step 1: Add the metrics block to `Instructions`** (start with `pmm_service_health`; read `pmm_catalog(kind: metrics)` before writing a query; aggregate first; filter by `service_name` or `service_id`; instant for now, range for trends; the language is MetricsQL), and assert it in `TestInitializeAndListTools`.
- [ ] **Step 2: Add api-tests** `TestServiceHealth` (MySQL, PostgreSQL, MongoDB service, one call each), `TestQueryMetricsBudget` (a broad accepted query is summarized and within 16 KiB), `TestListMetricsSearch`.
- [ ] **Step 3: Verify Access Roles live** on a Feature Build: a Viewer user (basic auth) with a role allowing one service gets only that service's series from `pmm_query_metrics` and `pmm_list_metrics` (names and label values). Service tokens wait for plan 06.
- [ ] **Step 4: Run the load test** (spec §7.5) on a VM with at least 50 services: five callers loop for 10 minutes over `rate(mysql_global_status_questions[5m])` without aggregation over 6 days, `rate(mysql_global_status_questions[7d])` as an instant query, and `{__name__=~"mysql_global_status_.*", service_name=~"<10 service names joined by |>"}`. Record VictoriaMetrics' CPU and memory and dashboard p95 latency, with and without the load, on PMM-15790 for the security review.
- [ ] **Step 5: Document the tools, budgets and errors in `mcp.md`; commit** `PMM-15790 Document and verify the metrics tools`.
