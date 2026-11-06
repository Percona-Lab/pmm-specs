# Metrics tools Implementation Plan

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans).

**Goal:** `pmm_query_metrics`, `pmm_list_metrics`, `pmm_service_health` and the metrics catalogue in `pmm_catalog`, each bounded in what it asks VictoriaMetrics to read and in what it returns.

**Architecture:** Every read goes through the Grafana datasource proxy (ADR-09) with a fixed set of arguments. Before a query is sent, `checkExpr` parses it with `metricsql` and enforces the execution budget; after, `shapeSeries` enforces the response budget. Metric calls use plan 02's `limiter` with their own counts.

**Tech Stack:** Go 1.27, go-sdk v1.8.0, `github.com/VictoriaMetrics/metricsql` v0.87.5 (Apache-2.0, new dependency; the API names below were checked at v0.84.3), VictoriaMetrics v1.154.0 behind vmproxy.

**Spec:** [ADR-15](../adr/ADR-15-metrics-tools.md), [spec §7.1, §7.4, §8](../spec.md#71-metrics), [ADR-09](../adr/ADR-09-metrics-via-datasource-proxy.md), [ADR-11](../adr/ADR-11-output-contract.md).

## Global Constraints

- Needs plan 02 (`limiter`, `callerKey`, `codeRateLimited`) and plan 03 (`addTool`, `window`, `page`, `partError`, `pmm_catalog`), and the design review (00).
- One branch, `PMM-15790-metrics-tools`, and one PR into `PMM-MCP-GA` after Task 9 ([00](00-roadmap.md#branch-and-pr-rules)).
- Every new tool follows 00's rules for new tools: `registerTools`, the name list of `TestInitializeAndListTools`, the tool lists of plan 03's `TestUntrustedFieldsMarked`, `TestErrorsCarryNoStructuredContent` and `TestRedactionInBothRenderings` (or its exemptions), and the golden file (`-update`). Every new `pmmAPI` method regenerates the mock (00).
- A service is looked up in the caller's service list (`listServices`, `engineOf`). Plan 06 later changes where that list comes from, to metric series (ADR-08); this plan calls only those two functions.
- **Execution budget** (`checkExpr`). Every refusal is `invalid_input` with a hint, before any request:
  - the expression is at most 4 KiB;
  - each OR group of a selector's label filters (`{a="x" or b="y"}`, one entry of `MetricExpr.LabelFilterss`) is a selector of its own, checked on its own; an expression has at most 10;
  - every selector names a metric: `__name__` with `=`, or with `=~` and a `regexp.LiteralPrefix` of at least 3 bytes;
  - a regex name also needs a scope in the same selector: a `service_id`, `service_name`, `node_id` or `node_name` matcher that is `=`, or `=~` whose every `|`-separated alternative parses (`regexp/syntax`) to a single literal. So `db1|db2` and `db\.prod` are scopes, and `.+` and `db.prod` are not;
  - the span read is the request's range plus the largest lookbehind of any path from the root to a selector. A path's lookbehind is the sum of the rollup windows, subquery ranges and `offset`s (absolute value) along it, so `max_over_time(rate(x[6d])[6d:1h])` reads 12 days. A path that reaches its selector through no rollup window, a bare selector (`up`) or the argument of a rollup function written without one (`rate(x)`), reads one step back [I], so it adds one `step`. The span is at most 7 days;
  - `@` is refused;
  - a MetricsQL `WITH` template is refused before parsing, since `metricsql.Parse` expands it before any check sees the expression;
  - a subquery's step is at least the span read ÷ 2,000; a subquery without a step takes the query's step, checked the same way.
- **Series selected** (`pmm_query_metrics`). Before a query runs, each selector is counted over the span read with the `series` endpoint and `limit=2001`; a selector over 2,000 series refuses the query with `invalid_input` and a hint to narrow it with a `service_*` or `node_*` matcher and aggregate (Task 4).
- **The one exception** to the selector rules is the name search of `pmm_list_metrics` (Task 5, ADR-15): it reads metric names only, from the label-values endpoint, with VictoriaMetrics' `limit` and a look-back of 1 hour by default and 7 days at most.
- Request arguments: `query`, `time` or `start`/`end`/`step`, and `timeout` for queries; `match[]`, `start`, `end` and `limit` for the list endpoints. Nothing else passes through. Times are Unix seconds, `step` whole seconds, `timeout` `25s` (spec §8: below the 30 s `callTimeout` of every backing call, `client.go:53`).
- Response budget:
  - 20 series by default, 100 maximum, top N by max;
  - 2,000 points and 16 KiB per response, the text and the structured content together;
  - summaries (min, avg, max, last) when raw points don't fit; a summary still over 16 KiB keeps fewer series, and says how many it left out;
  - NaN and ±Inf are `null`, with a note;
  - internal labels `agent_id`, `agent_type`, `node_id`, `machine_id`, `instance`, `job` dropped from rows; labels shared by every series shown once.
- Default range 1 h. `step` ≥ range / 2,000.
- **Bounded reads.** MCP reads at most 4 MiB of any response from the datasource proxy; a longer one fails the call, `invalid_input` with a hint to narrow for a model-written expression or selector, `pmm_unavailable` otherwise (Task 1).
- Concurrency: 4 metric calls per caller, 8 per replica. A call of `pmm_query_metrics`, `pmm_list_metrics` or `pmm_service_health` counts once, however many queries it runs. `pmm_top_queries` and `pmm_query_detail` take a slot of the same caps, and their window is at most 30 days (Task 8).
- **VictoriaMetrics requests.** Every request MCP sends to VictoriaMetrics, from any tool, takes a slot of one per-replica limit: metric calls, each `pmm_service_health` query, the version lookup, and the service list (plan 06) and alert list (plan 07), which build on `QueryInstant`. A request waits for a slot until its call's deadline. The limit is half of the `-search.maxConcurrentRequests` that PMM sets explicitly for its VictoriaMetrics (Task 1), so dashboards and alert evaluation keep slots.
- **Rate per caller.** A token bucket per caller key for live calls and one for metric calls (spec §8); an empty bucket answers `rate_limited` with `retry_after`, in seconds, in `_meta` (Task 8).
- **Supported fleet size:** Task 9 states it, from the load test, in spec §8 and `mcp.md`.
- Every map field in a result is `omitempty` or always non-nil: go-sdk checks an `object` schema and refuses `null`. The new tools join plan 03's `TestEmptyAndDegradedResults`.
- `pmm_service_health` derives no state of its own: no `stale`, no verdict. Each signal has its summary, `last_at` and source, or `no_data`, or an error.

## Review Focus

- **A model that asks for `rate(x[5m])` over exactly 7 days** gets a refusal that gives the span it would read and the cap, not a generic error: Task 2 tests the hint's span (`7d5m`) and cap.
- **An OR group without a metric name or a scope** is refused like a selector of its own: Task 2. metricsql copies a name matched with `=` into every group, but not a regex name, so `{__name__=~"mysql_global_status_.*", service_name="db1" or service_name="db2"}` has a second group with no name [V at v0.84.3].
- **A result with one huge series and many small ones** keeps the huge one in the top N and says how many were left out: Task 3 tests `total_series` and the hint.
- **One NaN from a ratio** arrives as `null` with a note; it never fails the call: Tasks 3 and 7.
- **VictoriaMetrics answering 422 for a bad expression** must surface as `invalid_input` with VictoriaMetrics' message, not `pmm_unavailable`: Task 1 tests the mapping.
- **Node signals under a service-filtered Access Role** report `no_data` with the note that it can mean "hidden", never a value or an error: Task 7 tests it.
- **A catalogue entry whose metric is missing from the captured exporter output** fails CI: Task 6's fixture test. It catches an upstream rename once the fixtures are captured again for the new exporter version; each fixture's header names the versions it came from.

---

### Task 1: Client calls with a fixed argument set

**Files:** Modify `managed/services/mcp/client.go`, `deps.go` (`pmmAPI`, `nullable`), `errors.go` (422), `helpers_test.go` (`fixture.body`, routing by query), `tools_inventory_test.go` and `tools_actions_test.go` (expected query strings), `managed/services/supervisord/supervisord.go` (the VictoriaMetrics flags), `managed/testdata/supervisord.d/victoriametrics*.ini`; Test `client_test.go` (new), `managed/services/supervisord/supervisord_test.go`.

**Interfaces:**
- Produces:
  - `const metricsTimeout = 25 * time.Second` in `client.go`.
  - `type promRequest struct { Query string; Time, Start, End time.Time; Step, Timeout time.Duration }` with `func (r promRequest) values() url.Values`: only the non-zero ones of `query`, `time`, `start`, `end` (Unix seconds), `step` (whole seconds), `timeout` (`25s`).
  - `type point struct { T time.Time; V float64 }`; `type metricSeries struct { Labels map[string]string; Points []point }`. Internal only; never marshalled.
  - `pmmAPI` gains:
    - `QueryRange(ctx context.Context, auth callerAuth, uid string, r promRequest) ([]metricSeries, error)`;
    - `LabelValues(ctx context.Context, auth callerAuth, uid, label string, match []string, start, end time.Time, limit int) ([]string, error)`;
    - `Labels(ctx context.Context, auth callerAuth, uid string, match []string, start, end time.Time, limit int) ([]string, error)`;
    - `Series(ctx context.Context, auth callerAuth, uid string, match []string, start, end time.Time, limit int) ([]map[string]string, error)`.
    `limit` is VictoriaMetrics' `limit` argument.
  - `QueryInstant` takes `(ctx, auth, uid string, r promRequest)`. Its one caller, `queryMetrics` (`tools_inventory.go:256-262`), passes `promRequest{Query: …, Time: at, Timeout: metricsTimeout}`.
  - `func nullable(v float64) *float64` in `deps.go`: nil for NaN and ±Inf, the values `finite()` (`deps.go:97-104`) turns into 0; the two share one check.
  - `mapError`: HTTP 422 becomes `invalid_input`, with VictoriaMetrics' message.
  - `const maxVMResponseBytes = 4 << 20`: every datasource-proxy response is read through `io.LimitReader`; one longer than that fails with `errResponseTooLarge`, which `pmm_query_metrics` and `pmm_list_metrics` answer as `invalid_input` with a hint to narrow, and every other tool as `pmm_unavailable`.
  - In `supervisord.go`, `--search.maxConcurrentRequests` joins the other `--search.*` flags of the VictoriaMetrics template, from `defaultVMSearchMaxConcurrentRequests`, overridable with `VM_search_maxConcurrentRequests` like them. Its default is VictoriaMetrics v1.154.0's own default on the smallest supported server (4 CPUs), read from its `-help` [I], so that size sees no change.
  - `client` gains a semaphore of `maxVMRequestsPerReplica` slots, half of the configured `-search.maxConcurrentRequests` (read the same way supervisord reads it), at least 1. `QueryInstant`, `QueryRange`, `LabelValues`, `Labels` and `Series` each hold one slot for the request; a request waits for a slot until its context ends, then fails with `timeout`.
  - `fixture` gains `body []byte`, served instead of `file` when set. A route key may end in ` ?<text>`: it matches a request with that method and path whose `query` parameter contains `<text>`, wins over the plain key (`helpers_test.go:81`), and the longest matching text wins. This is plan 06 Task 1's convention; whichever plan lands first adds it. One test can then answer several metric queries.

- [ ] **Step 1: Start the load-test server** of Task 9 Step 4 now, because it must collect for at least 6 days before the run: the smallest supported size, 4 CPUs and 8 GB (`documentation/docs/install-pmm/plan-pmm-installation/hardware_and_system.md:13-15`), from `PMM-MCP-GA`'s latest Feature Build, with at least 50 MySQL services (`pmm-admin add mysql --service-name db<N>` against a few instances is enough) and a steady workload on them.
- [ ] **Step 2: Write the tests:**
  - `TestPromRequestArguments`: for an instant and a range request, the recorded query string has exactly the expected keys (e.g. `query`, `start`, `end`, `step`, `timeout`) and `timeout=25s`; a zero `Time` sends no `time`;
  - `TestQueryRangeDecodes`: a matrix fixture into series and points, a `"NaN"` value kept as NaN;
  - `TestListCallsArguments`: each list call sends `limit`, `start`, `end` and the given `match[]`;
  - `TestMapError422`, `TestNullable`;
  - `TestVMResponseBounded`: a 5 MiB response fails with `errResponseTooLarge` after reading at most 4 MiB and a byte;
  - `TestVMRequestLimit`: with 2 slots, a third concurrent request waits until one returns; one whose context ends while it waits fails with `timeout` and sends nothing;
  - in `supervisord_test.go`, the VictoriaMetrics config carries `--search.maxConcurrentRequests` with the default, and with `VM_search_maxConcurrentRequests` set, that value;
  - the exact query strings of `TestInventoryTool` (`tools_inventory_test.go:77`) and `TestConfigTool` (`tools_actions_test.go:336`) gain `&timeout=25s`.
- [ ] **Step 3: Run, see FAIL; implement; regenerate the `pmmAPI` mock (00); run the package, see PASS.**
- [ ] **Step 4: Commit** `PMM-15790 Add range, label and series calls to the MCP client`.

### Task 2: Execution budget

**Files:** Create `managed/services/mcp/metrics_check.go`, `metrics_check_test.go`; Modify `go.mod` (`go get github.com/VictoriaMetrics/metricsql@v0.87.5`).

**Interfaces:**
- Produces: `const maxExprBytes = 4096`, `maxSelectors = 10`, `maxSpan = 7 * day`, `minNamePrefix = 3`; `func checkExpr(expr string, span, step time.Duration) error`.
- `metricsql.Parse`, then a recursive walk that carries each path's lookbehind (not `VisitAll`, which loses the path): `*FuncExpr` and `*AggrFuncExpr` (`Args`), `*BinaryOpExpr` (`Left`, `Right`), `*RollupExpr` (adds `Window` and `Offset`, refuses `At`, walks `Expr`), `*MetricExpr` (one selector per `LabelFilterss` entry; adds one `step` when no `RollupExpr` window is on its path). Durations use `DurationExpr.Duration(step.Milliseconds())`, so `i` units count; an instant query checks with `step` 5m, VictoriaMetrics' default [I].
- The time-read hint names the span, its parts and the cap, durations as days plus the rest: `the query reads 7d5m (range 7d + lookbehind 5m); the cap is 7d`.
- Before `metricsql.Parse`, the keyword `WITH` followed by `(`, case-insensitive and outside quoted strings, refuses the expression: "MetricsQL WITH templates are not accepted; write the expression out".
- A `*RollupExpr` that is a subquery (`Step` set, or `InheritStep`) has a step of at least the span read ÷ 2,000, the span as Global Constraints defines it; `InheritStep` uses `step`. The hint names the minimum.
- Check the metricsql names above at v0.87.5 after `go get`.

- [ ] **Step 1: Write `TestCheckExpr`**, table of `(expr, span, want error substring or "")`:

| expr | span | want |
|---|---|---|
| `rate(mysql_global_status_questions[5m])` | 6d | "" |
| `sum by (service_name) (rate(mysql_global_status_questions{service_name="db1"}[5m]))` | 1h | "" |
| `{__name__=~"mysql_global_status_.*", service_name=~"db1\|db2"}` | 1h | "" |
| `{__name__=~"mysql_global_status_.*", service_name=~"db\\.prod"}` | 1h | "" |
| `{__name__=~"mysql_global_status_.*", service_name=~"db.prod"}` | 1h | "service_id, service_name, node_id or node_name" |
| `{__name__=~"mysql_global_status_.*", service_name=~".+"}` | 1h | "service_id, service_name, node_id or node_name" |
| `rate(mysql_global_status_questions[7d])` | 0 | "" |
| `rate(mysql_global_status_questions[5m])` | 7d | "reads 7d5m", "the cap is 7d" |
| `{__name__=~".+"}` | 1h | "metric name" |
| `{job="mysql"}` | 1h | "metric name" |
| `{__name__!="up"}` | 1h | "metric name" |
| `{__name__="up" or service_name="db1"}` | 1h | "" (the `=` name is copied into both groups) |
| `{__name__=~"mysql_global_status_.*", service_name="db1" or service_name="db2"}` | 1h | "metric name" |
| `{job="x" or job="y"}` | 1h | "metric name" |
| `mysql_up{service_name="db1" or service_name="db2"}` | 1h | "" |
| `{__name__=~"mysql_global_status_.*", service_name="db1" or __name__=~"mysql_global_status_.*"}` | 1h | "service_id, service_name, node_id or node_name" |
| `{__name__=~"mysql_.*"}` | 1h | "service_id, service_name, node_id or node_name" |
| `{__name__=~"my.*", service_name="db1"}` | 1h | "prefix" |
| `rate(mysql_global_status_questions[365d])` | 0 | "the cap is 7d" |
| `rate(mysql_global_status_questions)` as a range query over 6 days with `step` 2d | 6d | "the cap is 7d" |
| `mysql_global_status_questions` as a range query over 6 days with `step` 2d | 6d | "the cap is 7d" |
| `max_over_time(rate(up[5m])[30d:5m])` | 0 | "the cap is 7d" |
| `max_over_time(rate(mysql_global_status_questions[4d])[4d:1h])` | 0 | "reads 8d" |
| `rate(mysql_global_status_questions[4d]) + rate(mysql_global_status_queries[4d])` | 0 | "" |
| `rate(mysql_global_status_questions[4d] offset 4d)` | 0 | "reads 8d" |
| `up offset 8d` | 0 | "the cap is 7d" |
| `up @ 1700000000` | 0 | "@" |
| `up @ start()` | 0 | "@" |
| `WITH (f(x) = rate(x[5m])) f(mysql_global_status_questions)` | 1h | "WITH" |
| `mysql_global_status_questions{service_name="with (db1)"}` | 1h | "" |
| `max_over_time(rate(mysql_global_status_questions[5m])[6d:1s])` | 0 | "subquery step" |
| `max_over_time(rate(mysql_global_status_questions[5m])[6d:5m])` | 0 | "" |
| 11 selectors joined by `+` | 1h | "10 selectors" |
| 6 selectors of two OR groups each, joined by `+` | 1h | "10 selectors" |
| 5,000-byte expression | 1h | "4 KiB" |
| `rate(` | 1h | "parse" |

- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.** `go test ./managed/services/mcp/ -run TestCheckExpr -v`. `make check-license` checks file headers only (`Makefile.include:54-55`): the new files carry the AGPL header, and the PR description states metricsql's Apache-2.0 license for review.
- [ ] **Step 3: Commit** `PMM-15790 Bound what a metrics query may read`.

### Task 3: Response budget

**Files:** Create `managed/services/mcp/metrics_budget.go`, `metrics_budget_test.go`.

**Interfaces:**
- Produces:
  - `const defaultSeries = 20`, `maxSeriesShown = 100`, `maxPoints = 2000`, `maxMetricsBytes = 16 << 10`, `defaultMetricsRange = time.Hour`.
  - `var internalLabels = []string{"agent_id", "agent_type", "node_id", "machine_id", "instance", "job"}`
  - `func chooseStep(span, requested time.Duration) time.Duration`: `max(requested, ceil(span/maxPoints) to the second, 1s)`; 0 for an instant query.
  - `type outPoint struct { T time.Time \`json:"t"\`; V *float64 \`json:"v"\` }`
  - `type seriesSummary struct { Labels map[string]string \`json:"labels"\` (Untrusted); Min, Avg, Max, Last *float64; LastAt time.Time \`json:"last_at"\`; Points []outPoint \`json:"points,omitempty"\` }`: min, avg and max over the finite points, nil when there is none; `Last` nil when the last value isn't finite. `Labels` is never nil: an empty map when every label is shared or internal.
  - `type metricsResult struct { Query string; Window *window; Step string; SharedLabels map[string]string (Untrusted, `omitempty`); Series []seriesSummary; TotalSeries int; Truncated bool; Summarized bool; Hint string; Note string }` (snake_case JSON) with `render()`: a header with the shared labels, one row per series with min, avg, max, last, then the hint and the note. Raw points go only in the structured content (ADR-11).
  - `func shapeSeries(expr string, series []metricSeries, limit int) metricsResult`, in this order: drop internal labels and move shared ones to `SharedLabels`; rank by max and keep the top `limit`; keep raw points when there are at most 2,000 and the size fits, else summaries; while the size still exceeds 16 KiB, drop the lowest-ranked series. The size is `len(render())` plus `len(json.Marshal(result))`. `TotalSeries` and the hint count every series left out; `Note` counts the values returned as `null`.

- [ ] **Step 1: Write `TestShapeSeries`:**
  - 300 series → 20 kept, ordered by max descending, `total_series` 300, `truncated`, hint contains `topk(10, <expr>)` and `sum by (service_name) (<expr>)`;
  - internal labels absent from every series; a label equal on all series moves to `shared_labels`;
  - 3 series × 50 points keep `points`; 20 series × 200 points (4,000) are `summarized` with no `points`; a result whose points exceed 16 KiB is summarized;
  - 100 series with long label values whose summaries exceed 16 KiB → fewer series, text plus JSON within 16 KiB, `total_series` 100, and the hint;
  - one NaN and one +Inf point → `null` in the JSON (`json.Marshal` succeeds), min, avg and max over the finite points, and a note naming 2 values;
  - one series whose labels are all internal → `labels: {}` and no `shared_labels`; the result passes the output schema.

  **`TestChooseStep`:** 1h → 2s, 6d → 260s (259.2 s rounded up), requested 5m on 1h → 5m.
- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Shape metrics results to a budget`.

### Task 4: `pmm_query_metrics`

**Files:** Create `managed/services/mcp/tools_metrics.go`, `tools_metrics_test.go`; Modify `mcp.go` (`Service.metrics *limiter`, set in `New`; `registerTools` calls `registerMetricsTools`), `mcp_test.go` (`pmm_query_metrics` in the name list).

**Interfaces:**
- Produces: `func (s *Service) registerMetricsTools(server *mcp.Server)`, which registers this task's tool and those of Tasks 5 and 7. `const maxSeriesPerSelector = 2000`; `func selectorsOf(expr string) ([]string, error)`: each selector of the parsed expression, one per OR group, in MetricsQL form; `func (s *Service) checkSeriesCount(ctx context.Context, auth callerAuth, uid string, selectors []string, start, end time.Time) error`: one `Series` call per selector, with `limit` 2,001, over the span read; more than 2,000 is `invalid_input` with the hint "this selector matches more than 2000 series over the span; narrow it with a service_name or node_name matcher, and aggregate". `type queryMetricsInput struct { Query string \`json:"query"\`; Time string \`json:"time,omitempty"\`; PeriodFrom string \`json:"period_from,omitempty"\`; PeriodTo string \`json:"period_to,omitempty"\`; Step string \`json:"step,omitempty"\`; Limit int \`json:"limit,omitempty"\` }`. `period_from` or `period_to` makes it a range query, with the window from `parseWindow` (`period_from` defaults to `now-1h`, so a `period_to` alone older than that is `invalid_input`); otherwise it is instant at `time` (default now). `time` with either period is `invalid_input`. `step` is a Go duration (`30s`, `5m`, `1h`), range queries only, in whole seconds; `1d`, `5i` and a `step` on an instant query are `invalid_input`. `limit` is 1 to 100, default 20. `const maxMetricCallsPerCaller = 4`, `maxMetricCallsPerReplica = 8`; `New` sets `s.metrics = newLimiter(maxMetricCallsPerCaller, maxMetricCallsPerReplica)`.

- [ ] **Step 1: Write `TestQueryMetricsTool`:** an instant and a range call against `body` fixtures (`/graph/api/datasources/name/Metrics`, `.../proxy/uid/<uid>/api/v1/query_range`); a refused expression records no request to the proxy; a 300-series response is cut to 20 with the hint; `limit: 101` is `invalid_input`; `time` with `period_from`, `step: 1d` and `step` without a period are `invalid_input`; `period_to` alone is a range query of the hour before it; with the caller's key at 4 on `s.metrics`, `rate_limited`; 8 other keys, `rate_limited`; a selector whose `series` answer has 2,001 entries refuses the query with that hint and no `query_range` request, and 2,000 passes; the description says "MetricsQL", "aggregate first", and gives one `sum by (service_name)` example.
- [ ] **Step 2: Run, see FAIL; implement (check → limiter → datasource uid → `checkSeriesCount` → client → `shapeSeries`); run the package, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Add pmm_query_metrics`.

### Task 5: `pmm_list_metrics`

**Files:** Modify `tools_metrics.go`, `tools_metrics_test.go`, `mcp_test.go` (`pmm_list_metrics` in the name list).

**Interfaces:**
- Produces:
  - `type listMetricsInput struct { Kind, Search, ServiceID, ServiceName, Label string; Match []string; PeriodFrom string; Limit, Offset int }` (snake_case JSON, all `omitempty`: `kind`, `search`, `service_id`, `service_name`, `label`, `match`, `period_from`, `limit`, `offset`).
  - `kind` picks the mode; an input the mode doesn't take, or an unknown `kind`, is `invalid_input`:

    | `kind` | Endpoint | Takes |
    |---|---|---|
    | `names` (default) | `/api/v1/label/__name__/values` | `search`, `service_id` or `service_name` |
    | `labels` | `/api/v1/labels` | `match` (optional) |
    | `values` | `/api/v1/label/<label>/values` | `label` (required), `match` (optional) |
    | `series` | `/api/v1/series` | `match` (required) |

  - `func nameSelector(search, serviceID, serviceName string) string`: `{__name__=~".*<s>.*"}` with `<s>` = `escapeLabel(regexp.QuoteMeta(search))` (`tools_qan.go:673-676`), plus `service_id="…"` or `service_name="…"`, also through `escapeLabel`. An empty `search` drops the name matcher, so the selector is the service matcher alone; with no service either, no `match[]` is sent and every name is listed, up to the limit. This is the exception in Global Constraints.
  - `type nameGroup struct { Prefix string \`json:"prefix"\`; Count int \`json:"count"\` }`; `func groupNames(names []string, limit int) ([]string, []nameGroup)`: over the limit, group by the first three `_`-separated parts (`mysql_global_status_*`); if still over, by the first two.
  - `type listMetricsResult struct { Kind string; Names []metricName; Groups []nameGroup; Labels []string (Untrusted); Values []string (Untrusted); Series []map[string]string (Untrusted); Page page; Hint string }`; `type metricName struct { Name, Meaning, Type string }` (meaning and type from the catalogue when present).
- Each `match` selector passes `checkExpr` with the look-back as span.
- `label` must match `^[a-zA-Z_][a-zA-Z0-9_]*$` and is path-escaped (`url.PathEscape`) into the URL.
- The look-back is 1 h by default and at most 7 days for every `kind`; a longer `period_from` is `invalid_input`.
- Every request carries `limit=1001`, one more than the maximum, and `start` and `end` for the look-back (1 h by default, from `period_from`). MCP sorts the answer and pages it with `offset` and `limit` (100 by default, 1,000 maximum): `page.total` is the count returned. When VictoriaMetrics returned more than 1,000, `page.truncated` is set and the hint says more than 1,000 match and to narrow the search.
- A call holds one slot on `s.metrics`.
- `names` over `limit` returns `groups` instead, paged the same way.
- `series` is also held to `maxMetricsBytes` (16 KiB), text and structured content together: series that don't fit are left out, `page.truncated` is set, and the hint says to narrow `match`. Each series map is non-nil.

- [ ] **Step 1: Write `TestListMetricsTool`:**
  - `search: ".*"` sends `match[]={__name__=~".*\\.\\*.*"}`: `QuoteMeta` escapes the regex, `escapeLabel` the MetricsQL string;
  - `search: mongodb` with `service_name: db1` adds `service_name="db1"`; `search` empty with no service sends no `match[]`;
  - every request carries `limit=1001`, `start` and `end`;
  - 1,500 names → groups with counts; 1,001 names from VictoriaMetrics → `truncated` with the hint;
  - `kind: labels` with `match: ["mysql_up"]` lists label names; `kind: values` without `label`, `kind: series` without `match`, and `kind: labels` with `search` are `invalid_input`;
  - `offset: 100` on 250 values returns values 101 to 200 and the marker;
  - `kind: series` with 500 series stays within 16 KiB and is `truncated`;
  - a catalogue name carries its meaning;
  - `match: ["{__name__=~\".+\"}"]` is `invalid_input`, with no request;
  - `kind: values` with `label: "../query"` is `invalid_input`, with no request;
  - `period_from: now-8d` is `invalid_input` for each `kind`, with no request; `now-7d` passes.

  **`TestNameSelector`**, **`TestGroupNames`**.
- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Add pmm_list_metrics`.

### Task 6: Metrics catalogue in `pmm_catalog`

**Files:** Create `managed/services/mcp/metrics_catalog.go`, `metrics_catalog_test.go`, `testdata/exporters/{mysql,postgresql,mongodb,node}.prom`; Modify `tools_catalog.go` (`kind: metrics`).

**Interfaces:**
- Produces: `type metricInfo struct { Name, Engine, Meaning, Unit, Type string; Labels []string; Query string }` (`Type`: `counter` or `gauge`; `Query`: a ready MetricsQL expression using `service_name="<service>"`); `var metricsCatalog []metricInfo`; `func metricInfoByName(name string) (metricInfo, bool)`. `catalogEntry` gains `Meaning`, `Unit`, `Type`, `Labels`, `Query`, with JSON tags `meaning`, `unit`, `type`, `labels`, `query` (all `omitempty`).
- `kind: metrics` without `engine` returns all four engines; `engine` is `mysql`, `postgresql`, `mongodb` or `node`. `node` is valid only with `kind: metrics`: `kind: qan_columns, engine: node` is `invalid_input`.
- **Selection rule.** An engine's candidates are the metrics with the engine's prefix named in the panel queries of its dashboards below, plus the metrics of its health signals (Task 7). Its entries are the candidates present in its exporter fixture (Step 1); the rest, such as the query cache metrics MySQL 8.0 no longer has, are left out.

  | Engine | Dashboards (`dashboards/dashboards/`) | Prefix | Candidates at `826945906` |
  |---|---|---|---|
  | `mysql` | `MySQL/MySQL_Instance_Summary.json` | `mysql_` | 59 |
  | `postgresql` | `PostgreSQL/PostgreSQL_Instance_Summary.json`, `PostgreSQL/PostgreSQL_Overview_Extended.json` | `pg_` | 42 |
  | `mongodb` | `MongoDB/MongoDB_Instance_Summary.json` | `mongodb_` | 34 |
  | `node` | `OS/Node_Summary.json` | `node_` | 41 |

  The candidates come from `jq -r '[.panels[] | (., (.panels // [])[])] | .[] | (.targets // [])[] | .expr // empty' <dashboards> | grep -oE '\b<prefix>[a-zA-Z0-9_]+' | sort -u`. `Meaning` is one line written by hand; `Unit` is the unit of the first panel that uses the metric (`fieldConfig.defaults.unit`, else `yaxes[0].format`); `Type` is the fixture's `# TYPE`; `Labels` are the label names on the metric's samples in the fixture. These are the exporter's own labels; vmagent adds PMM's target labels later, so they aren't there.

- [ ] **Step 1: Capture each exporter's output** on a client node, the way vmagent scrapes it, from a replica, so the replication metrics are present. Build the replicas with Docker on that node: a MySQL 8.0 source and replica (GTID on both; `CHANGE REPLICATION SOURCE TO SOURCE_HOST=…, SOURCE_AUTO_POSITION=1; START REPLICA`), a PostgreSQL 17 primary and a standby made with `pg_basebackup -R`, and a two-member MongoDB 7 replica set (`rs.initiate`). Register the replica, the standby and the secondary with `pmm-admin add mysql`, `postgresql` and `mongodb`, then capture from their exporters once per resolution, with that resolution's `collect[]` list from `managed/services/victoriametrics/scrape_configs.go` (`scrapeConfigsForNodeExporter` `:256`, `scrapeConfigsForMySQLdExporter` `:329`, `scrapeConfigsForMongoDBExporter` `:418`, `scrapeConfigsForPostgresExporter` `:477`), concatenated into one fixture per exporter:

  ```bash
  curl -sg -u "pmm:<agent_id>" "http://127.0.0.1:<port>/metrics?collect[]=<collector>&collect[]=<collector>…"
  ```

  `<agent_id>` and `<port>` are the exporter's Agent ID and Port from `pmm-admin list`; the password is the Agent ID unless the exporter has a password of its own (`managed/models/agent_model.go:563-570`). Write the exporter and PMM versions in each file's header comment.
- [ ] **Step 2: Write `TestMetricsCatalogMatchesExporters`** (every catalogue name appears in its engine's fixture; `counter` names end in `_total` or are typed `counter` in the fixture's `# TYPE`) and **`TestMetricsCatalogQueriesPass`** (each `Query`, with `<service>` replaced, passes `checkExpr` over 1 h).
- [ ] **Step 3: Run, see FAIL; write the catalogue; run, see PASS.** Extend `TestCatalogQANColumns` with `kind: metrics, engine: postgresql`, `kind: metrics` without `engine`, and `kind: qan_columns, engine: node` (`invalid_input`).
- [ ] **Step 4: Commit** `PMM-15790 Add the metrics catalogue to pmm_catalog`.

### Task 7: `pmm_service_health`

**Files:** Create `managed/services/mcp/tools_health.go`, `tools_health_test.go`, `testdata/health_*.json`; Modify `mcp_test.go` (`pmm_service_health` in the name list).

**Interfaces:**
- Consumes: `listServices` with node names, `listServices(ctx, auth, true)` until plan 06 drops the argument and always fills `NodeName`, `checkExpr`, `chooseStep`, `nullable`, `partErrorOf`, `serviceURL`.
- Produces:
  - `type serviceHealthInput struct { ServiceID string \`json:"service_id"\`; PeriodFrom string \`json:"period_from,omitempty"\`; PeriodTo string \`json:"period_to,omitempty"\` }`; the window comes from `parseWindow`, the last hour by default.
  - `type signal struct { Name, Unit, Source, Query string; Node bool }`; `Query` uses `%[1]s` wherever the selector goes (`service_name="…"` or, when `Node`, `node_name="…"`), since most targets name it twice (`rate(…) or irate(…)`); `Source` is the first metric the query names. `var healthSignals = map[string][]signal{…}`, from the table below.
  - `type signalResult struct { Name, Unit, Source string; Min, Avg, Max, Last *float64; LastAt *time.Time \`json:"last_at,omitempty"\`; NoData bool \`json:"no_data,omitempty"\`; Error *partError \`json:"error,omitempty"\` }` (snake_case JSON; `error.message` is Untrusted, as in plan 03's `partError`).
  - `type healthResult struct { ServiceID string; ServiceName string (Untrusted); Engine string; Window window; Signals []signalResult; Partial bool; Note string; PMMURL string }`.
- **Signals.** Each query is the named dashboard target, with `$service_name` (and `$secondary`) replaced by the service's name and `$node_name` by its node's, each of those matchers made `=`; every other template variable (`$database`, `$environment`, `$cluster`, `$rs_nm`) replaced by `.*`; and `$interval`, `$__interval` and `$__rate_interval` by `5m`. A target that returns one series per label value is aggregated as the table says. Dashboard files are under `dashboards/dashboards/`.

  | Engine | Signal | Dashboard uid: panel, target | Unit |
  |---|---|---|---|
  | all (node) | `cpu_busy` | `node-instance-summary`: CPU Usage, B, `sum by (node_name)` | percent |
  | all (node) | `load1` | `node-instance-summary`: Load Average, A | short |
  | all (node) | `memory_available` | `node-instance-summary`: Memory Available, A | percent |
  | all (node) | `disk_read_latency` | `node-instance-summary`: Disk IO Latency, A | s |
  | all (node) | `disk_write_latency` | `node-instance-summary`: Disk IO Latency, B | s |
  | all (node) | `min_space_available` | `node-instance-summary`: Min Space Available, A | percent |
  | mysql | `qps` | `mysql-instance-summary`: Current QPS, A | short |
  | mysql | `threads_connected` | `mysql-instance-summary`: MySQL Connections, A | short |
  | mysql | `max_connections` | `mysql-instance-summary`: MySQL Connections, B | short |
  | mysql | `threads_running` | `mysql-instance-summary`: MySQL Client Thread Activity, B | short |
  | mysql | `aborted_connects` | `mysql-instance-summary`: MySQL Aborted Connections, A | ops |
  | mysql | `slow_queries` | `mysql-instance-summary`: MySQL Slow Queries, A | ops |
  | mysql | `tmp_disk_tables` | `mysql-instance-summary`: MySQL Temporary Objects, B | short |
  | mysql | `replication_lag` | `mysql-replicaset-summary`: MySQL replication lag, A | s |
  | mysql | `buffer_pool_miss_ratio` | `mysql-innodb`: BP Miss Ratio, A | percentunit |
  | postgresql | `connections` | `postgresql-instance-summary`: Connections, C | short |
  | postgresql | `commits` | `postgresql-instance-summary`: Transactions, A | ops |
  | postgresql | `rollbacks` | `postgresql-instance-summary`: Transactions, B | ops |
  | postgresql | `deadlocks` | `postgresql-instance-summary`: Conflicts/Deadlocks, A | ops |
  | postgresql | `max_tx_duration` | `postgresql-instance-summary`: Duration of Transactions, A, `max by (service_name)` | s |
  | postgresql | `replication_lag` | `postgresql-replication-overview`: Max Replication Lag, A | s |
  | postgresql | `cache_hit_ratio` | `postgresql-overview-extended`: Min Cache Hit Ratio, A | percentunit |
  | mongodb | `qps` | `mongodb-instance-summary`: QPS, A | ops |
  | mongodb | `latency` | `mongodb-instance-summary`: Latency, A | µs |
  | mongodb | `connections` | `mongodb-instance-summary`: Connections, J | short |
  | mongodb | `queued_operations` | `mongodb-instance-summary`: Queued Operations, J, `sum by (service_name)` | short |
  | mongodb | `query_efficiency` | `mongodb-instance-summary`: Query Efficiency, A | percentunit |
  | mongodb | `asserts` | `mongodb-instance-summary`: Assert Events, J, `sum by (service_name)` | short |
  | mongodb | `page_faults` | `mongodb-instance-summary`: Page Faults, J | short |
  | mongodb | `replset_state` | `mongodb-instance-summary`: Current ReplSet State, A | none |
  | mongodb | `replication_lag` | `mongodb-replicaset-summary`: Replication Lag, A | s |

- **One call.** A `service_id` not in the caller's service list is `not_found`. The call holds one slot on `s.metrics` and runs its signal queries at most 4 at a time, each holding a slot of the VictoriaMetrics request limit (Task 1), so its fan-out counts per query; each a range query over the window, with `chooseStep` for the window's length. Each query passes `checkExpr` with the window's length as span; a window too long for that is `invalid_input` before any query.
- Each signal reports min, avg, max and last over its finite points, through `nullable`, and `last_at`, the newest sample time; or `no_data` when the query returns no series. When a node signal is `no_data`, `note` says that an Access Role that filters on service labels hides node series, so `no_data` can mean "hidden" as well as "not sent".
- A signal whose query fails has `error` (`partErrorOf`), and the result is `partial`. When every signal fails, the call fails with the first error (ADR-11).
- **Deadline.** The signal queries share a deadline 10 s before the call's own (`PMM_MCP_ACTION_TIMEOUT` + 45 s, 60 s by default), so the result is built in time. A signal still running then gets `error.code: timeout`. Each query also carries `timeout=25s`.

- [ ] **Step 1: Write `TestServiceHealthTool`**, with fixtures routed by query text (Task 1):
  - a MySQL fixture returns every signal with min, avg, max, last and `last_at`;
  - a signal whose series ends 20 minutes before `period_to` reports that `last_at`, and no other state;
  - an empty node signal is `no_data`, and `note` says it may be hidden by an Access Role;
  - a signal whose query answers 422 has `error.code: invalid_input`, the others still return, and the result is `partial`; when every signal fails, the call is an error result;
  - a NaN from a ratio gives `last: null` and the note, and the call succeeds;
  - called with a context 11 s from its deadline, a signal whose fixture never answers gets `error.code: timeout` after about 1 s, and the result is `partial`;
  - the call holds one slot on `s.metrics`, whatever the number of signals, and one VictoriaMetrics request slot per query in flight;
  - no field is a healthy or unhealthy verdict, and no field is `stale`;
  - `service_id` outside the caller's list is `not_found`;
  - the node signals' queries carry `node_name="<the service's node>"`, from the service list.

  **`TestHealthSignalsPass`:** every query, filled in, passes `checkExpr` over 1 h, and every metric it names is in its engine's or the node's exporter fixture (Task 6).
- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Add pmm_service_health`.

### Task 8: QAN calls and per-caller rate limits

**Files:** Modify `managed/services/mcp/limits.go` (`rateLimiter`, `startLive`), `errors.go` (`toolError`, `errorResult`), `tools_qan.go`, `tools_metrics.go`, `tools_health.go`, `mcp.go` (`New`); Test `limits_test.go`, `errors_test.go`, `tools_qan_test.go`, `tools_metrics_test.go`.

**Interfaces:**
- `pmm_top_queries` and `pmm_query_detail` take a slot on `s.metrics`, as metric calls do, with the same `rate_limited` messages.
- `const maxQANWindow = 30 * day`: a longer window for `pmm_top_queries` or `pmm_query_detail` is `invalid_input` before any QAN call, and the message gives the cap.
- `type rateLimiter struct` (a mutex, a rate per second, a burst, and a bucket per caller key) with `func newRateLimiter(perMinute, burst int) *rateLimiter` and `func (r *rateLimiter) take(key string, now time.Time) (time.Duration, bool)`: it takes one token, or returns the wait until the next one. A bucket that has refilled to its burst is deleted, so the map holds only recent callers.
- `New` sets `s.liveRate = newRateLimiter(10, 4)` and `s.metricRate = newRateLimiter(60, 10)` (spec §8). `startLive` takes a token from `s.liveRate`, and `pmm_query_metrics`, `pmm_list_metrics` and `pmm_service_health` from `s.metricRate`, before their slot, by `callerKey`. QAN calls take no token.
- `toolError` gains `retryAfter time.Duration`. An empty bucket answers `rate_limited` with "too many calls for these credentials; retry in <n> s", and `errorResult` adds `retry_after`, whole seconds rounded up, to `_meta.com.percona/error` when it is set (`tool-contract.md` §3.1).

- [ ] **Step 1: Write the tests:**
  - `TestRateLimiter`: the burst passes, the next call is refused with a wait of 1/rate, a token comes back after that wait, another key has its own bucket, and an idle bucket is deleted;
  - `TestRateLimitedRetryAfter`: five live calls from one caller in quick succession, each finishing at once: the fifth answers `rate_limited` with `retry_after` ≥ 1 in `_meta` and the same number in the text; another caller's call passes; the same for eleven metric calls;
  - `TestQANWindowCap`: `pmm_top_queries` and `pmm_query_detail` over 31 days answer `invalid_input` with no QAN call; 30 days pass;
  - `TestQANCallsShareMetricSlots`: with the caller's key at 4 on `s.metrics`, `pmm_top_queries` and `pmm_query_detail` answer `rate_limited`;
  - `TestRetryable` (plan 03) still passes: `retry_after` doesn't change `retryable`.
- [ ] **Step 2: Run, see FAIL; implement; run the package, see PASS.**
- [ ] **Step 3: Commit** `PMM-15790 Rate-limit MCP calls per caller`.

### Task 9: Instructions, docs, live checks and the load test

**Files:** Modify `mcp.go` (`Instructions`), `documentation/docs/api/mcp.md`; Test `mcp_test.go`, `api-tests/mcp/mcp_test.go`; Create `api-tests/mcp/load_test.go` (build tag `load`).

- [ ] **Step 1: Add the metrics block to `Instructions`** (start with `pmm_service_health`; read `pmm_catalog(kind: metrics)` before writing a query; aggregate first; filter by `service_name` or `service_id`; instant for now, range for trends; the language is MetricsQL), and assert `pmm_service_health` and `MetricsQL` in `TestInitializeAndListTools`.
- [ ] **Step 2: Add api-tests:**
  - `TestServiceHealth`: one call each for the MySQL, PostgreSQL and MongoDB services; every signal has `last_at` or `no_data`, and none has `error`;
  - `TestQueryMetricsBudget`: `{__name__=~"mysql_global_status_.*", service_name="<the MySQL service>"}` over the last 6 hours is summarized, and its text plus structured content is within 16 KiB;
  - `TestListMetricsSearch`: `search: mongodb` returns only names containing `mongodb`; `search: ".*"` returns none; with no `search`, `page.total` is at most 1,001, so VictoriaMetrics honours `limit` [I: a server with every engine registered has more than 1,001 metric names].
- [ ] **Step 3: Verify Access Roles live** on the Feature Build: a Viewer user (basic auth) with an Access Role allowing one service gets only that service's series from `pmm_query_metrics`, its names and label values from `pmm_list_metrics`, and `no_data` with the note for the node signals of `pmm_service_health`. Service-account tokens wait for plan 06.
- [ ] **Step 4: Run the load test** ([spec §7.4](../spec.md#74-acceptance)) on the server Task 1 Step 1 started:
  - **Server:** the one from Task 1 Step 1, upgraded to this branch's Feature Build; it has collected for at least 6 days, so the 6-day queries read 6 days of data.
  - **Driver:** `go test -tags load ./api-tests/mcp/ -run TestMetricsLoad -timeout 30m`, with `PMM_MCP_LOAD_TOKENS` set to a file of five Viewer service-account tokens, one per caller (an environment variable, because `api-tests/init.go` parses the flags before the test registers any). Each caller runs two loops for 10 minutes; each loop calls `pmm_query_metrics` with, in turn:
    - `rate(mysql_global_status_questions[5m])` as a range query over the last 6 days;
    - `rate(mysql_global_status_questions[6d])` as an instant query;
    - `{__name__=~"mysql_global_status_.*", service_name=~"db1|db2|db3|db4|db5|db6|db7|db8|db9|db10"}` as a range query over the last 6 days.

    Each caller also runs a third loop of `pmm_service_health` over `db1` to `db10` in turn, each over the last 6 hours. The driver records each call's latency and result code, `rate_limited` included: fifteen loops against the 8-per-replica cap.
  - **Dashboard latency:** during the run the driver also sends the MySQL queries of Task 7's signal table for `db1`, over the last 12 hours with `step=60s`, every 10 s, as Admin straight through `/graph/api/datasources/proxy/uid/<uid>/api/v1/query_range`, and reports their p95 latency. The same probe runs alone for 10 minutes first, as the baseline.
  - **VictoriaMetrics CPU and memory:** from PMM's own scrape of VictoriaMetrics (job `victoriametrics`, `managed/services/victoriametrics/victoriametrics.go:425`): `rate(process_cpu_seconds_total{job="victoriametrics"}[1m])` and `process_resident_memory_bytes{job="victoriametrics"}`, their maximum and p95 over each 10-minute run, read as Admin.
  - **Alert evaluation:** the increase over each run of the rule-evaluation failure counters of Grafana's alerting and of VMAlert, from PMM's scrape of both (jobs `grafana` and `vmalert`) [I: metric names checked on the Feature Build], read as Admin.
  - **Pass:** the loaded run adds no rule-evaluation failure beyond the baseline's, and the dashboard probe's p95 under load is at most twice the baseline's. Otherwise lower the caps in spec §8 through a pmm-specs PR, then here, and run again.
  - **Record** both runs (CPU, memory, dashboard p95, rule-evaluation failures, MCP call count and p95, `rate_limited` count) on PMM-15790 for the security review.
  - **Fleet size:** state the number of monitored services the passing run had as the supported fleet size, in spec §8 through a pmm-specs PR and in `mcp.md`.
- [ ] **Step 5: Document the tools, budgets and errors in `mcp.md`, with the rate limits and `retry_after`, the 30-day QAN window, the supported fleet size, and that label values are returned as stored (ADR-07); commit** `PMM-15790 Document and verify the metrics tools`.
- [ ] **Step 6: Open the PR** ([00](00-roadmap.md#branch-and-pr-rules)): merge `origin/PMM-MCP-GA` (behind 0) into the branch, run a Feature Build, run the api-tests and the triage on it, and open `PMM-15790 Add the MCP metrics tools` into `PMM-MCP-GA` with the Feature Build link.
