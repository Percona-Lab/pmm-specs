# Service list and Access Roles Implementation Plan

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans).

**Goal:** Every service lookup in MCP uses the caller's service list, built from the `up` series the caller can read, so MCP's results follow the caller's Access Roles (ADR-08, ADR-03). The Viewer inventory rules from #5942 are removed. Once PMM-15534 is merged in from `main`, service-account tokens are governed by Access Roles too (ADR-12), and an api-test matrix proves it for every MCP tool.

**Architecture:** MCP first forwards the caller's credentials in ADR-10's canonical form. `listServices` then stops calling the inventory API: it runs one instant query through the Grafana datasource proxy (ADR-09), which vmproxy filters by the caller's Access Roles, and builds one row per `service_id` from the `up` series of the call's window, at most its last 7 days, or of the last hour for a call without a window. `pmm_inventory`, `engineOf`, `serviceEngine`, `pinnedServiceID`, the resolve-first candidates, the `pmm_query_detail` narrowing, `pmm_get_config` and `pmm_service_health` all read that list. pmm-managed's APIs, nginx, the gRPC gateway and `lbacPrefixes` don't change: ADR-16 is deferred.

**Tech Stack:** Go 1.27, go-sdk v1.8.0, MetricsQL `tlast_over_time` through the datasource proxy (VictoriaMetrics v1.154.0 behind vmproxy; metricsql v0.87.5 lists the function in `rollup.go:87` [V]), api-tests.

**Spec:** [ADR-08](../adr/ADR-08-inventory-under-access-roles.md), [ADR-12](../adr/ADR-12-service-accounts-as-principals.md), [ADR-03](../adr/ADR-03-api-only-data-path.md), [ADR-09](../adr/ADR-09-metrics-via-datasource-proxy.md), [ADR-10](../adr/ADR-10-nginx-only.md), [spec §9](../spec.md#9-phase-4-identity-and-access-roles), [tool-contract §3.2, §7, §8](../tool-contract.md#8-tools). Ticket PMM-15531. PMM-15534 is its own ticket on `main`.

**Code base:** percona/pmm `PMM-15790-metrics-tools` at `ac98fee31`: plan 05 complete, [percona/pmm#6291](https://github.com/percona/pmm/pull/6291), not yet merged into `PMM-MCP-GA`. Line numbers refer to that commit, and are those of `747e1f968` outside `api-tests/mcp/load_test.go`; paths are under `managed/services/mcp/` unless they say otherwise. [V] marks what was read there, [I] what was not checked.

## Global Constraints

**Branches, PRs and commits**
- Branch `PMM-15531-service-list`, cut from `origin/PMM-15790-metrics-tools`, not from `PMM-MCP-GA`. Task 1 builds on plan 05's code: `QueryInstant(ctx, auth, uid, r promRequest)` (`client.go:433`, called by `queryMetrics`, `tools_inventory.go:336-342`), its VictoriaMetrics semaphore and 4 MiB read cap (`getVM`, `client.go:593-603`), and the fake PMM's routing by query text (`fakePMM.route`, `helpers_test.go:116-139`) [V]. When #6291 merges, the branch merges `origin/PMM-MCP-GA` (Task 5) and its PR targets `PMM-MCP-GA`.
- PMM-15534 is not on `main` (2026-11-07: no commit, no branch). So two PRs:
  - PR 1, from this branch: Tasks 1, 2 and 4 without the service-account token rows; Task 5 lands it.
  - PR 2: Task 3 and the token rows, from branch `PMM-15531-service-account-roles`, cut from `PMM-MCP-GA` once PR 1 is merged and `main` with PMM-15534 is merged into `PMM-MCP-GA` (00).
  - Execution order: Tasks 1, 2, 4, 5, then 3. If PMM-15534 reaches `PMM-MCP-GA` before Task 5 starts, Task 3 runs before Task 5 and one PR carries all of it.
- Commit titles `PMM-15531 <summary>`, at most 50 characters, signed off (`git commit -s`); a new commit per review round (00).

**Pre-push checks.** The last step of every task, from the percona/pmm root. `<base>` is `origin/PMM-15790-metrics-tools` until Task 5 merges `origin/PMM-MCP-GA`, then `origin/PMM-MCP-GA`. `make init` installs `bin/golangci-lint` once.

```bash
go test -race ./managed/services/mcp/...        # and the other packages the task names
go vet ./managed/services/mcp/... ./api-tests/...
bin/golangci-lint run --new-from-rev=<base> ./managed/... ./api-tests/...
make gen
make format
git status --short   # if anything changed: git add those files; git commit -s -m "PMM-15531 Apply make gen and make format"
git push -u origin HEAD
```

CI's "Checks" job runs `make gen` and `make format` and fails on any diff (00), so their output is committed, in a commit of its own, as plan 05 did (`747e1f968`) [V]. api-tests packages are vetted, not run: their `init` waits for a live server (`api-tests/init.go:183-189`) [V].

**Live-check environment** (00), for Task 1's timing step and Tasks 4, 5 and 3:
- PMM Server and Client images from a Feature Build: a draft PR in Percona-Lab/pmm-submodules whose `ci.yml` pins `pmm` to the branch under test (`deps:` `- name: pmm` `branch: PMM-15531-service-list`), on a throwaway CHAOS VM.
- Access Control is enabled (`PUT /v1/server/settings`, `{"enable_access_control": true}`) before any database is registered.
- MySQL 8.0, PostgreSQL 17 with pg_stat_monitor and MongoDB 7, plus the services Task 4 adds.

**The caller's service list** (ADR-08, spec §9.2)
- **Look-back** (user decision, 2026-11-09; spec §8). A call with a window reads the `up` series of that window, ending at the window's end, and at most its last 7 days; a call without a window reads the last hour.
  - With a window: `pmm_service_health` (`period_from`, `period_to`); `pmm_query_detail` (its period); `pmm_get_explain` and `pmm_get_schema` in a query form (the window of the `query_ref` or of the flat period, the last hour by default); and `pmm_top_queries`' two lookups, `pinnedServiceID` and `serviceEngine`, over the report's window.
  - `pmm_get_config` reads one instant, `at`: its list covers the hour before `at`, the hour its QAN link covers (`tools_config.go:187`) [V]. With the default `at`, that is the last hour.
  - Without a window: `pmm_inventory`, and `pmm_get_schema` with named tables (`engineOf`).
  - A longer window, up to the QAN tools' 30 days (`maxQANWindow`, `tools_qan.go:192`) [V] or longer for `pmm_get_explain` and `pmm_get_schema`, reads its last 7 days, and a `not_found` says so.
- Built from every `up` series of the look-back, of any `service_type`, read through the datasource proxy with the caller's credentials, by one instant query at the look-back's end (`time`), with the look-back in whole seconds, as `parseWindow` truncates windows to the second (`time.go:82-99`) [V]:

  ```text
  max by (service_id, service_name, service_type, node_id, node_name, environment, cluster) (tlast_over_time(up[<seconds>s]))
  ```

  The value is the newest sample time in Unix seconds; `tlast_over_time` counts every sample, whatever its value.
- Every row with a non-empty `service_id` is a service: one per `service_id`, from its row with the newest `last_seen`, with `service_name`, engine (its `service_type`), `node_id`, `node_name`, `environment`, `cluster` and `last_seen`. Rows without `service_id` (node_exporter's, PMM Server's own jobs) give no service.
- Only `service_id` is required. PMM removes empty labels before they reach a scrape target (`prepareLabels`, `managed/models/models.go:107-127`; `UnifiedLabels`, `managed/models/service_model.go:115-137`) [V], so a missing label is an empty field.
- No address and no port.
- Any `up` value counts. A target scraped with `up=0` stays listed with a current `last_seen`. A service leaves the list only when no `up` sample at all arrived in the look-back, for example when its pmm-agent or vmagent stopped.
- Sorted by engine, then service name, then `service_id`. Two services can share a name within the look-back, after one is removed and another added under its name, of the same engine or not; every lookup by name takes the one with the newest `last_seen` (`serviceNamed`, Task 1).
- Built per tool call with the caller's own credentials, never cached or shared between callers (ADR-03). A failing list query fails the tool call; it never falls back to an unfiltered source.
- The query goes through `queryMetrics` and `QueryInstant`, so it takes a slot of plan 05's limit on requests to VictoriaMetrics and is read within its 4 MiB cap; a longer answer is `pmm_unavailable` (`mapError`, `errors.go:119-121`) [V].
- **Cost of the list query.**
  - Time read: at most 7 days, plan 05's cap on a metrics query (`maxSpan`, `metrics_check.go:35`) [V]; `TestServiceListQueryInBudget` (Task 1) pins it. The list query is MCP's own, so it skips `checkExpr` and the series cap.
  - Samples: at PMM's default resolutions, 5 s, 10 s and 60 s (`managed/models/settings.go:275-281`) [V], a standard exporter's three `up` series (hr, mr, lr jobs; node_exporter's at `scrape_configs.go:267-310`) [V] hold 120,960 + 60,480 + 10,080 = 191,520 samples over 7 days [V]. Task 4's environment, 8 services and 2 nodes or about 11 exporters [I: the exporter count], reads about 2.1 million samples for a 7-day list and 1/168 of that for an hour. VictoriaMetrics' `-search.maxSamplesPerQuery` is 1,500,000,000 (`managed/services/supervisord/supervisord.go:53`) [V].
  - Response: one row per label set seen in the look-back, about 300 bytes with PMM's UUID IDs (`managed/models/service_helpers.go:298`) [V; the label lengths are I], so about 3.3 KB for Task 4's 11 rows [I]. The 4 MiB cap holds about 14,000 rows. A service renamed or registered again within the look-back adds a row, so a fleet that churns fills it faster over 7 days than over an hour.
  - Latency: Task 1 Step 16 measures it for 1 hour, 24 hours and 7 days.
- After Task 1, no MCP tool calls `/v1/inventory/`. After Task 2, `GET /v1/inventory/services` and `/nodes` are Admin-only again.

**Lookups and errors**
- A `service_id` or service name outside the list answers `not_found` (`errNotInList`, Task 1): the fixed text `notInServiceList` (`resolve.go:33`) [V], from Task 1 "not in your service list (services that sent metrics in the window searched)"; then "; searched <from> – <to>", the look-back as `windowText` prints it (`resolve.go:243-245`) [V], with ", the last 7 days of the call's window" when a longer window was cut; then the tool's existing hint, "; use pmm_inventory to list service ids" where the tool has it today (`tools_qan.go:931`, `tools_health.go:309`) [V]. A `not_found` message never echoes the ID or name the caller sent, and no error text, hint or candidate list names a service outside the list (tool-contract §3.2).
- `pmm_get_explain`, `pmm_get_schema` and `pmm_get_config` keep their engines and their existing `invalid_input` for another `service_type` (`tools_actions.go:293`, `:514-519`; `tools_config.go:145-150`) [V]. `pmm_service_health` answers `invalid_input` for a service that is neither MySQL, PostgreSQL nor MongoDB, before any signal query (Task 1): tool-contract §8 gives it those engines, and with node signals alone the result would read as a service that sent nothing.
- pmm-managed's APIs, nginx, the gRPC gateway and `lbacPrefixes` are unchanged.
- **Credentials on backing calls** (ADR-10). Before the list moves to the Grafana-served datasource proxy, MCP forwards the caller's credentials in one canonical form: when `auth.GetTokenFromHeaders` (`managed/utils/auth/token.go:33-52`) [V] finds a token, `Authorization: Bearer <token>` and no `Cookie`; otherwise Basic `Authorization` and `Cookie` unchanged. Task 1 does this first, in its own commit.
- Every contract change regenerates `testdata/tools_list.golden.json` (`go test ./managed/services/mcp/ -run TestToolsListGolden -update`), and removing `pmmAPI` methods regenerates the mock as 00 says.

**Deviation from the task-level plan.** This plan builds the services of the list only. The list's nodes (every distinct `node_id` and `node_name` in any row, node_exporter's included) have no caller before plan 07's `pmm_alerts`. `unparam`, enabled with `check-exported: true` (`.golangci.yml:101-102`) [V], fails on a result no caller reads, and `AGENTS.md` asks for no speculative options. Plan 07 Task 2 adds them on the same query, which already groups by the node labels. The look-back is a parameter here, as the task-level plan had it (`listServicesOver`), now as the call's window: its callers pass different windows, so `unparam` has nothing to report.

## Review Focus

- **A service with no `up` sample in the last hour,** for example in push mode with its pmm-agent stopped, leaves `pmm_inventory`. A call whose window covers a time it sent samples still finds it, up to 7 days back: health over the last 6 hours of a service stopped 3 hours ago answers. A window over 7 days searches its last 7 days, and a `not_found` says so. A target that is scraped but down (`up=0`) stays listed with a current `last_seen`. Task 1 tests the window, the cut and the query (no comparison on `up`); Task 5 checks it live.
- **A service or node renamed within the hour** gives one row, with the newest labels; **a service removed and re-added under its name** gives two rows, and every lookup by name takes the newer, whatever their engines (Task 1, `TestServiceList`, `TestConfigByServiceName`).
- **A service without `environment` or `cluster`,** the default, is listed like any other (Task 1).
- **A restricted Admin:** vmproxy filters an Admin's metrics by Access Role like anyone else's: PMM adds filters for every user ID above 0 (`maybeAddLBACFilters`, `managed/services/grafana/auth_server.go:428-433`) [V]. So an Admin with a restricted Access Role gets a filtered list too (Task 4).
- **Service-account tokens before PMM-15534 is merged in** resolve to user ID 0 (`getAuthUser`, `managed/services/grafana/client.go:296-305`) [V] and see every service; Task 3 is the gate, and plan 08 checks it before the merge back.
- **One `queryid` recorded on an allowed and on a hidden service:** `pmm_query_detail`, `pmm_get_explain` and `pmm_get_schema` return the allowed one or `not_found`, never the hidden one's data or name. PostgreSQL stored plans are included: PMM-15697's fix (`a98506570`) is in this branch, and qan-api2's plan query applies the caller's filter and the `service_id` (`SelectQueryPlan`, `qan-api2/models/metrics.go:952-968`) [V] (Task 4).
- **A service that an Access Role hides, passed to `pmm_service_health`:** before this plan the list came from the inventory, so the tool answered with every signal `no_data` and a note. From Task 1 it is outside the list and answers `not_found` with the fixed text and hint, naming nothing. The all-`no_data` note stays, reworded, for a listed service whose signals are all empty (Task 1).
- **A ProxySQL, HAProxy, Valkey or external service** is listed by `pmm_inventory`. `pmm_get_schema` with named tables, `pmm_get_config` and `pmm_service_health` refuse it with `invalid_input`, and the query tools find no QAN data for it (Task 1).

---

### Task 1: Canonical credentials, and the caller's service list from series (ADR-10, ADR-08)

**Files:**
- Modify:
  - `deps.go` (`callerAuthFromHeader` `:42-48`, `pmmAPI` `:176-194`);
  - `client.go` (`AuthenticateRequest` comment `:205-206`; delete `ListServices` `:312-319`, `ListNodes` `:321-328` and the `inventory` client field `:134`, `:198`);
  - `doc.go` ("verbatim" `:23-24`);
  - `tools_inventory.go` (`serviceInfo` `:52-60`, `serviceRow` `:72-81`, `render` `:89-122`, description `:136-137`, `inventory` `:171-222`, `listServices` `:224-263`; delete `nodeNames` `:265-290`);
  - `tools_qan.go` (`pinnedServiceID` `:263-281` and its call `:242`, `serviceEngine` `:836-850` and its call `:782`, `queryDetail`'s `callerServices` call `:553`, `engineOf` `:923-934`);
  - `resolve.go` (`notInServiceList` `:33`, `resolveQuery`'s `callerServices` call `:101`, `callerServices` `:166-187`);
  - `tools_config.go` (`config` `:104-196`);
  - `tools_health.go` (`allNoDataNote` `:38`, `serviceHealth` `:303-311`);
  - `links.go` (`serviceURL` `:69-80`);
  - `mcp.go` (`Instructions` item 2, `:41-42`);
  - `mock_pmm_api_test.go` (regenerated), `helpers_test.go`, `testdata/tools_list.golden.json`;
  - `documentation/docs/api/mcp.md`.
- Test data: create `testdata/vm_up_list.json`, `vm_up_services.json`, `vm_up_many.json`, `vm_up_quoted_ids.json`, `vm_mongodb_version.json`; delete `services.json`, `services_with_mongo.json`, `services_many.json`, `services_quoted_ids.json`, `nodes.json`.
- Test: `client_test.go`, `tools_inventory_test.go`, `tools_actions_test.go`, `hardening_test.go`, `tools_health_test.go`, `tools_qan_test.go`, `resolve_test.go`, `contract_test.go`, `mcp_test.go`, `api-tests/mcp/mcp_test.go` (`TestInventory` `:326-362`).

**Interfaces:**
- Consumes: `queryMetrics(ctx, auth, promql string, at time.Time) ([]metricSample, error)` (`tools_inventory.go:336`), `metricSample{Labels map[string]string; Value float64}` (`deps.go:58-61`), `type window struct { From, To time.Time }` (`results.go:74-77`), `windowText` (`resolve.go:243`), `day` (`time.go:27`), `hourWindow` (`mcp.go:73`), `checkExpr(expr string, span, step time.Duration) (time.Duration, error)` (`metrics_check.go:78`), `notInServiceList`, `mapError`, `paginate`, `enrichVersions` [V].
- Produces:
  - `callerAuthFromHeader(h http.Header) callerAuth`: with a token, `authorization` is `"Bearer " + token` and `cookie` is empty; otherwise both as received. `AuthenticateRequest` and `apply` (`client.go:207-231`) set them on every backing call as today; `callerKey` (`limits.go:169-199`) still keys by the token.
  - In `tools_inventory.go`: `const serviceListQuery`, the query in Global Constraints verbatim with `%d` for the seconds (`...tlast_over_time(up[%ds]))`); `const maxListLookback = 7 * day`; `const engineProxySQL = "proxysql"`, `engineHAProxy = "haproxy"`, `engineValkey = "valkey"`, `engineExternal = "external"`; `var serviceTypes = []string{engineMySQL, enginePostgreSQL, engineMongoDB, engineProxySQL, engineHAProxy, engineValkey, engineExternal}`, PMM's service types (`managed/models/service_model.go:42-48`) [V].
  - `type serviceInfo struct { ServiceID, ServiceName, Engine, Version, NodeID, NodeName, Environment, Cluster string; LastSeen time.Time }`. `Address` and `Port` go.
  - `func listSpan(w window) (window, bool)`: the look-back for a call window `w`: `To` is `w.To`, `From` is the later of `w.From` and `w.To - maxListLookback`, and the bool says whether it cut `w`.
  - `func (s *Service) lastHour() window`: `window{From: s.now().Add(-hourWindow), To: s.now()}`, the look-back of a call without a window.
  - `func (s *Service) listServices(ctx context.Context, auth callerAuth, w window) ([]serviceInfo, error)`: runs `fmt.Sprintf(serviceListQuery, <seconds of listSpan(w)>)` with `queryMetrics` at `listSpan(w).To`, and applies Global Constraints' rules. `LastSeen` is the value as Unix seconds, truncated to the second, in UTC. `Version` stays empty. The `withNodeNames` argument goes. Its callers pass, per Global Constraints:
    - `inventory` (`tools_inventory.go:181`): `s.lastHour()`;
    - `serviceHealth` (`tools_health.go:303`): `window{start, end}`;
    - `config`: `window{at.Add(-hourWindow), at}`;
    - `engineOf` (`tools_qan.go:925`): `s.lastHour()`; its signature stays, and after Task 1 its one caller is `pmm_get_schema` with named tables (`tools_actions.go:384`);
    - `callerServices(ctx context.Context, auth callerAuth, serviceID string, w window) ([]serviceInfo, []string, error)` (`resolve.go:166-167`), called by `resolveQuery` with `window{ref.PeriodFrom, ref.PeriodTo}` (`resolve.go:101`) and by `queryDetail` with `window{from, to}` (`tools_qan.go:553`);
    - `pinnedServiceID(ctx context.Context, auth callerAuth, labels map[string][]string, w window) string` (`tools_qan.go:263`, `:271`), called by `topQueries` with `window{from, to}` (`:242`);
    - `serviceEngine(ctx context.Context, auth callerAuth, name, id string, w window) string` (`tools_qan.go:836`, `:840`), called by `reportEngine` with `window{from, to}` (`:782`).
  - `const notInServiceList = "not in your service list (services that sent metrics in the window searched)"`; `func errNotInList(w window, hint string) *toolError`: `not_found` with `notInServiceList + "; searched " + windowText(span)`, then `", the last 7 days of the call's window"` when `listSpan(w)` cut `w`, then `hint`. Every `not_found` for a service outside the list goes through it: `engineOf` and `serviceHealth` with the hint `"; use pmm_inventory to list service ids"`, `pmm_get_config` likewise, `callerServices` (`resolve.go:179`, `:184`) with none. It names the window, never a service.
  - `func serviceNamed(services []serviceInfo, name string) (serviceInfo, bool)`: among the services with that name, the one with the newest `LastSeen`. Every lookup by name goes through it: `pinnedServiceID` (`tools_qan.go:276`), `serviceEngine` (`:845`), `queryCandidates` (`resolve.go:213`) and `pmm_get_config`.
  - `type serviceRow struct`, JSON in this order: `service_id`; `service_name` (Untrusted); `engine`, described "PMM service type: mysql, postgresql, mongodb, proxysql, haproxy, valkey or external."; `version` (Untrusted, `omitempty`); `node_id` (`omitempty`); `node_name` (Untrusted, `omitempty`); `environment` (Untrusted, `omitempty`); `cluster` (Untrusted, `omitempty`); `last_seen` (`time.Time`), described "Time of the service's newest up sample, whatever its value."; `pmm_url` (`omitempty`). `address` and `port` go.
  - `inventoryResult.render()`: each row is `- <service_name> | <engine> <version or unknown> | id=<service_id> | node=<node_name> | environment=<environment> | cluster=<cluster> | last_seen=<RFC 3339, UTC> | [View in PMM ↗](<pmm_url>)`, with the `node`, `environment`, `cluster` and link parts left out when empty. With no service: "No services found in your service list (services that sent metrics in the last hour)."
  - `pmm_inventory`'s description: "List the monitored services in your service list: those whose up series you can read and that sent metrics in the last hour, with service type, version, node, environment, cluster and last_seen. Use this to discover a service_id / service_name and the exact engine version before analysing a query."
  - `inventoryInput.Engine` is described "Filter by service type: mysql, postgresql, mongodb, proxysql, haproxy, valkey or external". Another value is `invalid_input`, "engine must be one of mysql, postgresql, mongodb, proxysql, haproxy, valkey, external; got '<engine>'", before any call. The filter applies after the query: `engine` matches the service type exactly; `node` matches `node_name` exactly, as today.
  - `enrichVersions` keeps its three engines (`versionMetrics`, `tools_inventory.go:45-49`); another service type reports `unknown` in text, and no `version` in structured content, as today [V].
  - `engineOf` keeps its signature and its hint (`tools_qan.go:924-934`) [V]; its `not_found` goes through `errNotInList` for the last hour.
  - `pmm_get_config` makes one `listServices` call: by `service_id` when given (it wins over `service_name`, as today), else by `service_name`. Not found answers `errNotInList` for the hour before `at`, with `engineOf`'s hint. The engine comes from the list unless the caller gives one; an explicit engine wins, as today (`tools_config.go:136-139`) [V].
  - `pmm_service_health`: a service outside the list answers `errNotInList(window{start, end}, "; use pmm_inventory to list service ids")`, in place of today's text (`tools_health.go:309`). One of another type answers `invalid_input`, "pmm_service_health covers MySQL, PostgreSQL and MongoDB services; service '<name>' is <type>; use pmm_query_metrics for its metrics", before any signal query. `allNoDataNote` becomes: "no_data on every signal means that the service sent none of these metrics in the window although its up series is there, for example because its exporter could not be scraped or could not reach the database; an Access Role that filters on service labels can also hide its node's series." The list covers the window, so the service sent `up` samples in it.
  - `serviceURL(base, svc)`: MySQL, PostgreSQL, MongoDB as today. HAProxy: `graph/d/haproxy-instance-summary?var-service_name=<service_name>`. ProxySQL: `graph/d/proxysql-instance-summary?var-proxysql=<node_name>`, because that dashboard selects by node (`proxysql` variable = `label_values(proxysql_mysql_status_active_transactions, node_name)`; its targets filter `node_name="$proxysql"`, `dashboards/dashboards/MySQL/ProxySQL_Instance_Summary.json`) [V], omitted when the node name is empty. Another type: no link.
  - `Instructions` item 2 becomes, on two lines: "2. pmm_inventory - list the services that sent metrics in the last hour" / "(service_id, service_name, engine, last_seen); pick one to investigate." `TestInitializeAndListTools` keeps its cap of `< 34` newlines (`mcp_test.go:49`; 33 today) [V].
  - In `helpers_test.go`: `const serviceListKey = vmQuery + " ?tlast_over_time(up["`; `func listQueries(f *fakePMM) int`, the recorded requests to `vmAPI + "query"` whose `query` contains `tlast_over_time(up[`; and `fakePMM.serve` calls `f.t.Errorf` for any request whose path starts with `/v1/inventory/`, so no test can pass while a tool still calls the inventory.

- [ ] **Step 1: Write `TestBackingCallCredentials`** in `client_test.go`. It calls `pmm_version` (a generated client) and `pmm_query_detail` with `queryid: QID-AAA` (raw requests, and the generated `getExample`) through `connectWithHeaders` (`helpers_test.go:218`) against `qanRoutes()`, once per header set, and checks every request the fake PMM recorded:

  | Caller sends | Every backing call carries |
  |---|---|
  | `Authorization: Bearer glsa_x`, `Cookie: pmm_session=s1` | `Authorization: Bearer glsa_x`, no `Cookie` |
  | Basic `api_key:glsa_x`, `Cookie: pmm_session=s1` | `Authorization: Bearer glsa_x`, no `Cookie` |
  | Basic `service_token:glsa_x`, `Cookie: pmm_session=s1` | `Authorization: Bearer glsa_x`, no `Cookie` |
  | Basic `alice:pw`, `Cookie: pmm_session=s1` | both unchanged |
  | `Cookie: pmm_session=s1` alone | the `Cookie` unchanged, no `Authorization` |

  It also asserts that `callerKey(callerAuthFromHeader(h))` is equal for the three token forms.
- [ ] **Step 2: Run, see FAIL.** `go test ./managed/services/mcp/ -run TestBackingCallCredentials -v`; expected: the two Basic token forms arrive as Basic, and the cookie arrives with the tokens.
- [ ] **Step 3: Implement `callerAuthFromHeader`** (Interfaces), and change the comments that say "verbatim" (`deps.go:34-36`, `client.go:205-206`, `doc.go:23-24`). In `mcp.md`, "How it works" (`:9`) says that a token goes to PMM's API as `Authorization: Bearer <token>` without cookies, and Basic credentials and a session cookie as sent.
- [ ] **Step 4: Run `go test ./managed/services/mcp/...`, see PASS; commit** `PMM-15531 Forward canonical credentials`.
- [ ] **Step 5: Write the fixtures.** VictoriaMetrics instant-vector answers, `[1789387200, "<last_seen>"]` per row (`testNow` is 1789387200, `tools_qan_test.go:38`) [V]:
  - `vm_up_list.json`, for `TestServiceList`:
    1. `svc-1`, `shop-mysql`, `mysql`, `node-1`, `demo-node`, `environment` `prod`, `cluster` `c1`: `1789387140`;
    2. `svc-1` again with `node_name` `old-node`: `1789384200`;
    3. `svc-2`, `shop-postgres`, `postgresql`, `node-1`, `demo-node`, no `environment` or `cluster`: `1789387140.567`;
    4. `node-2`, `bare-host`, no service label: `1789387140`;
    5. `svc-px`, `proxy-1`, `proxysql`, `node-1`, `demo-node`: `1789387140`;
    6. `svc-re-old`, `shop-re`, `mysql`, `node-1`, `demo-node`: `1789384200`; 7. `svc-re-new`, `shop-re`, `postgresql`, `node-1`, `demo-node`: `1789387140`. The older sorts first, so a lookup by list order would pick it;
    8. no label at all (PMM Server's own jobs): `1789387140`.
  - `vm_up_services.json`, the services of `services_with_mongo.json` and the node names of `nodes.json` (`svc-1` `shop-mysql`, `svc-2` `shop-postgres` and `svc-mongo` `shop-mongo` on `node-1` `demo-node`; `svc-pmm-pg` `pmm-server-postgresql` on `pmm-server` `pmm-server`), plus a node-only row for each node, all at `1789387140`.
  - `vm_up_many.json`: `svc-bulk-00` to `svc-bulk-24`, `bulk-mysql-00` to `bulk-mysql-24`, `mysql`, `node-1` `demo-node`, as `services_many.json`.
  - `vm_up_quoted_ids.json`: `svc-o'1`, `shop-mysql`, as `services_quoted_ids.json`.
  - `vm_mongodb_version.json`: `mongodb_version_info{service_name="shop-mongo", mongodb="7.0.14"}`.
  - `vm_up_window.json`: `vm_up_services.json`'s rows plus `svc-gone`, `shop-gone`, `mysql`, `node-1`, `demo-node`, last seen `1789376400` (`testNow` − 3 h), which no 1-hour list holds.
- [ ] **Step 6: Write the tests,** and add `serviceListKey`, `listQueries` and the inventory guard to `helpers_test.go` (Interfaces):
  - `TestServiceList` (`tools_inventory_test.go`), calling `s.listServices` directly against `serviceListKey` → `vm_up_list.json`:
    - with `s.lastHour()`: one datasource lookup and one request to `/graph/api/datasources/proxy/uid/metrics-uid/api/v1/query`, whose `query` is `fmt.Sprintf(serviceListQuery, 3600)` verbatim, with `time=1789387200`, `timeout=25s` and the caller's `Authorization`; no other request, so no version query;
    - the result is exactly, in order: `svc-1` (`shop-mysql`, `node-1`, `demo-node`, `prod`, `c1`, 11:59:00Z), `svc-re-old` (11:10:00Z), `svc-2` (empty `Environment` and `Cluster`, 11:59:00Z after truncation), `svc-re-new` (11:59:00Z), `svc-px` (`proxysql`); rows 4 and 8 give no service;
    - `serviceNamed(services, "shop-re")` returns `svc-re-new`; an unknown name returns false;
    - `serviceListQuery` has no comparison on `up`, so a target whose last sample is `up=0` is listed;
    - `listSpan`: a 1-hour and a 7-day window come back unchanged and uncut; a 30-day window ending at `testNow` becomes 2026-09-07T12:00:00Z – 2026-09-14T12:00:00Z, cut;
    - the proxy answering 401 returns an error that `mapError` maps to `unauthorized`, not an empty list; a 5 MiB answer is `pmm_unavailable`.
  - `TestInventoryTool`, rewritten on `vm_up_services.json`, with the version routes `vmQuery + " ?mysql_version_info"`, `" ?pg_static"` and `" ?mongodb_version_info"`:
    - rows carry `last_seen` and no `address` or `port`; each engine's version comes from its own fixture;
    - `vm_empty.json` as the list gives the empty-list text;
    - on `vm_up_list.json`: `engine: proxysql` returns `proxy-1` with `pmm_url` `graph/d/proxysql-instance-summary?var-proxysql=demo-node`; `shop-mysql`'s row has `| environment=prod | cluster=c1 |`; `shop-postgres` has neither;
    - `engine: valkey` is accepted and returns the empty-list text; `engine: oracle` is `invalid_input` with no request;
    - the `node` filter, paging and the 401 answer as today;
    - the description contains "sent metrics in the last hour".
  - `TestServiceListQueryInBudget` (`tools_inventory_test.go`): `checkExpr(fmt.Sprintf(serviceListQuery, 604800), 0, 0)` returns no error and a time read of 7 days, plan 05's cap.
  - `TestListFollowsTheWindow` (`tools_inventory_test.go`), with `serviceListKey` → `vm_up_services.json` and `vmQuery + " ?tlast_over_time(up[14400s]"` → `vm_up_window.json` (Step 5), so the longer route text wins for the 4-hour window:
    - `pmm_service_health` with `service_id: svc-gone` and no window is `not_found`, ending `; searched 2026-09-14T11:00:00Z – 2026-09-14T12:00:00Z; use pmm_inventory to list service ids`, without `svc-gone` or `shop-gone`;
    - with `period_from: now-6h, period_to: now-2h` it answers, and its list request has `up[14400s]` and `time=1789380000`;
    - `pmm_query_detail` and `pmm_get_explain` with `queryid: QID-AAA`, `service_id: svc-gone` and that window get past the list: a `qan:getMetrics` and a `getReport` request carry `svc-gone`;
    - `pmm_top_queries` with `service_name: shop-gone`, `group_by: queryid` and that window gives its rows a `query_ref.service_id` of `svc-gone`;
    - `pmm_query_detail` with `service_id: svc-secret` and `period_from: now-30d` sends `up[604800s]` at `time=1789387200`, and answers `not_found` ending `; searched 2026-09-07T12:00:00Z – 2026-09-14T12:00:00Z, the last 7 days of the call's window`, without `svc-secret`;
    - `pmm_get_config` with `service_id: svc-1` and `at: now-3h` sends `up[3600s]` at `time=1789376400`.
  - `TestEngineOfOutsideList` (`tools_actions_test.go`): `pmm_get_schema` with `service_id: svc-secret`, `database: shop`, `tables: [orders]` answers exactly `error: not_found\n` + `errNotInList(s.lastHour(), "; use pmm_inventory to list service ids")`'s text. The message contains neither `svc-secret` nor any other service's name or ID, and no action starts.
  - `TestConfigByServiceName` (`hardening_test.go`, next to `TestConfigAcceptsServiceID` `:216`):
    - `service_name: shop-mysql` returns its variables;
    - `shop-re` on `vm_up_list.json` resolves to `svc-re-new`: the variables query carries `pg_settings_`, not `mysql_global_variables_`;
    - a name outside the list is `not_found` with `errNotInList` for the hour before `at`, without the name, and sends no request to the proxy other than the list query;
    - `service_name: proxy-1` is `invalid_input` naming `proxysql`.
  - `TestServiceHealthTool` (`tools_health_test.go`):
    - `NotInTheServiceList` (`:367-377`) expects `errNotInList` for the last hour, with its hint, and asserts no `query_range` request; it no longer asserts that the datasource was not looked up, because the list reads it;
    - new `OtherServiceType`: `svc-px` on `vm_up_list.json` is `invalid_input` with the message above and no `query_range` request;
    - `EverySignalIsNoData` (`:236-250`) asserts the new `allNoDataNote`, which no longer says that an Access Role hides the service's own series;
    - `NoNodeName` (`:404-418`) gets its unknown node from a list row without `node_name`, not from a failing `/v1/inventory/nodes`.
  - `TestLinks` (`tools_qan_test.go:793-817`): the ProxySQL and HAProxy links above; a ProxySQL service without a node name, and `valkey`, give "".
  - `TestInitializeAndListTools` asserts `sent metrics in the last hour` in `Instructions`.
- [ ] **Step 7: Run, see FAIL.** `go test ./managed/services/mcp/ -run 'TestServiceList|TestInventoryTool|TestEngineOfOutsideList|TestConfigByServiceName|TestServiceHealthTool|TestLinks|TestInitializeAndListTools' -v`
- [ ] **Step 8: Implement** the Interfaces: `listServices`, `serviceNamed`, the inventory, config, health and link changes, the callers' new signature, `Instructions`. Delete `nodeNames`.
- [ ] **Step 9: Remove `ListServices` and `ListNodes`** from `pmmAPI` and `client`, with their imports. Run `go tool mockery --config .mockery.yaml` from the repository root, then `make format`, and commit only `managed/services/mcp/mock_pmm_api_test.go` (00).
- [ ] **Step 10: Move every test off the inventory API,** those of plans 04 and 05 included. `inventoryRoutes()` (`tools_inventory_test.go:29-37`) serves `GET /graph/api/datasources/name/Metrics`, `serviceListKey` and the three version routes, so `qanRoutes`, `resolveRoutes`, `explainRoutes`, `healthRoutes` and `actionRoutes`, which build on it, follow. Then:

  | Today | After |
  |---|---|
  | `GET /v1/inventory/services` with `services.json` or `services_with_mongo.json`, and `GET /v1/inventory/nodes` with `nodes.json` | `serviceListKey` with `vm_up_services.json` |
  | `services_many.json` (`resolve_test.go:149`) | `vm_up_many.json` |
  | `services_quoted_ids.json` (`resolve_test.go:219`) | `vm_up_quoted_ids.json` |
  | `empty.json` on the services route (`contract_test.go:382`, `resolve_test.go:212`, `tools_qan_test.go:593`) | `vm_empty.json` on `serviceListKey` |
  | `failed` or an error on the services or nodes route (`contract_test.go:385`, `:394`, `:551-552`; `tools_qan_test.go:380`; `tools_inventory_test.go:201`, `:214`; `tools_health_test.go:407`) | the same fixture on `serviceListKey`; the nodes cases become a list row without `node_name` |
  | `requestsTo("/v1/inventory/services")` or `"/nodes"` (`hardening_test.go:322`, `:377`; `resolve_test.go:291`; `tools_actions_test.go:1021`; `tools_inventory_test.go:181`; `tools_qan_test.go:344`, `:375`, `:840`) | `listQueries(fake)`, with the same count |
  | the text `notInServiceList` (`hardening_test.go:280`; `resolve_test.go:171`, `:215`, `:222`, `:331-332`; `tools_actions_test.go:470`; `tools_health_test.go:373`; `tools_qan_test.go:546`, `:598`) | the text `errNotInList` gives for the call's window and hint |

  A test whose expectation relied on routing by path alone changes with it. For example, `TestConfigAcceptsServiceID/ResolvesIDToName` (`hardening_test.go:222-248`) now reads version `8.0.46-37`, because the version query has its own route. `contract_test.go`'s `versionQuery` scenario fails the three version routes, not the plain query route. Delete the five inventory fixtures; `grep -rn 'v1/inventory' managed/services/mcp/` then finds no test route.
- [ ] **Step 11: Update the contract tests.** In `TestUntrustedFieldsMarked` (`contract_test.go:158`), `pmm_inventory`'s list is `services[].service_name`, `services[].node_name`, `services[].version`, `services[].environment`, `services[].cluster` (tool-contract §7). Regenerate the golden file with `-update`.
- [ ] **Step 12: Run `go test ./managed/services/mcp/...`, see PASS.**
- [ ] **Step 13: Rewrite api-test `TestInventory`** (`api-tests/mcp/mcp_test.go:326-362`):
  - add `func upRows(t *testing.T, authorization string) []map[string]string`: the Metrics datasource's uid from `/graph/api/datasources/name/Metrics`, then the rows of the service-list query for the last hour, its text copied verbatim with `up[3600s]`, from `/graph/api/datasources/proxy/uid/<uid>/api/v1/query`, both with `authorization`;
  - add `func adminAuthorization() string`: the Basic value of `-pmm.server-url`'s user;
  - for each row with a `service_id`, `pmm_inventory`'s text has `- <service_name> | <service_type> ` and `id=<service_id>`, and `page.total` is the number of distinct `service_id`s;
  - no row of the text contains `address=`; every `last_seen` is within the last hour;
  - `engine: mysql` returns no other type; `engine: oracle` is `invalid_input`.

  `topQueryID`, `monitoredService` and `TestSchemaFromQueryID` keep reading the inventory as Admin. `go vet ./api-tests/...` passes.
- [ ] **Step 14: Update `mcp.md`.**
  - The `pmm_inventory` row (`:99`): its fields, and the datasource proxy's `/api/v1/query` on `up` with the version metrics as its backing API.
  - The rows of `pmm_query_detail`, `pmm_get_explain`, `pmm_get_schema`, `pmm_service_health` and `pmm_get_config` (`:101-108`) lose `GET /v1/inventory/services` and name the service list.
  - The links table (`:118`) adds ProxySQL and HAProxy.
  - "The query tools see only your service list" (`:393`) states the look-back (the call's window, at most its last 7 days, said in the error when cut; the last hour for `pmm_inventory` and named tables; the hour before `at` for `pmm_get_config`), `up=0`, `last_seen`, that Access Roles filter the list, and that QAN can show a service the list lacks (spec §9.2).
  - The `pmm_service_health` paragraph (`:279`): the new note, and that a service outside the list, one an Access Role hides included, is `not_found`.
  - "Versions come from metrics" (`:395`): another service type reports `unknown`.
- [ ] **Step 15: Commit** `PMM-15531 Build the MCP service list from series`.
- [ ] **Step 16: Time the list query.** This needs no code from this plan; any PMM Server with at least 50 services and a week of data does, such as plan 05's load-test server (plan 05 Task 1 Step 1) while it runs. As Admin, through `/graph/api/datasources/proxy/uid/<uid>/api/v1/query`, time the query with `[1h]`, `[24h]` and `[7d]`, 20 runs each (`curl -w '%{time_total}'`). Record the p50 and p95, the number of services, the rows returned and the days of data on PMM-15531, and in ADR-08's Consequences through a pmm-specs PR. The look-backs are spec §8's: the call's window up to 7 days, 1 hour without a window, and 7 days for `pmm_alerts` (ADR-17); a pmm-specs PR changes spec §8 if the 7-day cost calls for it.
- [ ] **Step 17: Run the pre-push checks** (Global Constraints) and push.

### Task 2: Remove the Viewer inventory rules (ADR-08)

**Files:**
- Modify: `managed/services/grafana/auth_server.go` (`methodRules`: the comment and two entries at `:161-167`) [V], `documentation/docs/api/mcp.md` (the Roles table, `:356`)
- Test: `managed/services/grafana/auth_server_test.go` (`TestResolveRule`, `:127-138`) [V]

**Interfaces:** none.

- [ ] **Step 1: Change `TestResolveRule`.** The comment at `:127` says inventory reads are Admin except `services:getTypes`. `GET /v1/inventory/services`, `/v1/inventory/services/svc-1` and `/v1/inventory/nodes` expect `admin`, and a new case `GET /v1/inventory/nodes/node-1` expects `admin`. `/v1/inventory/services:getTypes` stays `viewer` through its own rule (`auth_server.go:94`) [V].
- [ ] **Step 2: Run, see FAIL.** `go test ./managed/services/grafana/ -run TestResolveRule -v`
- [ ] **Step 3: Delete the two entries and their comment;** run again, see PASS.
- [ ] **Step 4: Update `mcp.md`.** `pmm_inventory` joins the Viewer row of the Roles table: it reads no inventory API, only the metrics the caller can read.
- [ ] **Step 5: Commit** `PMM-15531 Keep inventory reads Admin-only`.
- [ ] **Step 6: Run the pre-push checks,** with `go test -race ./managed/services/grafana/ -run 'TestResolveRule|TestNextPrefix'` added: other tests of that package need a live Grafana (00). Push.

### Task 4: Access Role matrix for the MCP tools (api-tests)

**Files:**
- Create: `api-tests/accesscontrol_helpers.go` (package `apitests`, imported as `pmmapitests`), `api-tests/mcp/access_roles_test.go`, `api-tests/mcp/testdata/shop-postgresql.sql`
- Modify:
  - `api-tests/init.go`: the flag `-pmm.run-mcp-access-role-tests` [`PMM_RUN_MCP_ACCESS_ROLE_TESTS`] beside `-pmm.run-mcp-workload-tests` (`:107-108`, `:120`), and `accesscontrolClient.Default`, set next to the other clients (`:172-181`) [V];
  - `api-tests/mcp/mcp_test.go` (`connectWith`);
  - `documentation/docs/api/mcp.md` (Limitations, `:386`).

**Interfaces:**
- Consumes: `upRows`, `adminAuthorization` (Task 1); `callRetrying`, `callTool`, `callResult` (`api-tests/mcp/mcp_test.go:99-155`) [V].
- Produces:
  - `func connectWith(t *testing.T, authorization string) *mcp.ClientSession`: a session that sends this `Authorization`, a Bearer token or Basic credentials, on every request.
  - In package `apitests`, modelled on the unexported helpers of `api-tests/accesscontrol/accesscontrol_test.go` (`setup` `:332-440`, `createGrafanaUser` `:512-532`, `setAccessControl` `:469-479`) [V]. That package keeps its own `TestMain` setup and is not switched over. Each helper fails the test on error and registers its undo with `t.Cleanup`:
    - `SetAccessControl(t *testing.T, enabled bool)`: restores the previous setting;
    - `CreateRole(t *testing.T, title, filter string) int64`: deletes the Access Role;
    - `AssignRoles(t *testing.T, userID int64, roleIDs ...int64)`: replaces the user's Access Roles, as PMM's `AssignRoles` does (`managed/models/role_helpers.go:38-61`) [V];
    - `SetDefaultRole(t *testing.T, roleID int64)`: restores the previous `default_role_id` (`api/server/v1/server.proto:173`). PMM refuses to delete the default Access Role (`role_helpers.go:93-95`) [V]; cleanups run last-in-first-out, so the default is restored before `CreateRole`'s cleanup deletes the role;
    - `CreateUser(t *testing.T, login, password, grafanaRole string) int64`: `POST /graph/api/admin/users`, then `PATCH /graph/api/org/users/<id>` with the Grafana role, as `api-tests/server/auth_test.go:276-325` does; it deletes the Grafana user.
  - In `access_roles_test.go`: `func waitForServiceList(t *testing.T, authorization string, want []string)` polls `upRows(t, authorization)` once a second for up to 20 s, until the set of `service_name`s of its rows with a `service_id` equals `want`. pmm-managed caches the Access Control setting for a few seconds (`managed/services/grafana/access_control_cache.go:39-46`) [V]. On timeout it logs the last set with `t.Logf` and returns, so the assertions report what the server does.
  - `TestAccessRoleMatrix`, skipped unless `-pmm.run-mcp-access-role-tests` is set, and not `t.Parallel()`: it changes server-wide settings, and every principal first seen while the default Access Role is changed keeps that role (`getLBACFilters`, `auth_server.go:484-531`) [V].

**Environment:** the live-check environment, plus these services on the one pmm-client node, each pair from the same image and initialisation:
- `mysql-a` and `mysql-b`, MySQL 8.0 with perfschema and query examples on (the default);
- `pg-a` and `pg-b`, PostgreSQL 17 with `shared_preload_libraries = 'pg_stat_monitor'` and `pg_stat_monitor.pgsm_enable_query_plan = on`, registered with `--query-source=pgstatmonitor`.

The workload follows plan 04 Task 7 Step 4:
- **MySQL:** on each of `mysql-a` and `mysql-b`, load `managed/services/mcp/testdata/explain/schema.sql`, then run `join-aliases.sql` from the same folder 100 times in one `mysql` session on database `shop`, ending with `SELECT SLEEP(10)`, so pmm-agent samples the query example from `events_statements_history` (`api-tests/mcp/mcp_test.go:385-391`) [V].
- **PostgreSQL:** no PostgreSQL version of `schema.sql` exists in the repository (`testdata/explain/` holds MySQL files only) [V]. `shop-postgresql.sql` ports its `customers` and `orders` tables, indexes and rows: indexes as `CREATE INDEX`, no `ENGINE`, and `ANALYZE customers, orders` at the end. On each of `pg-a` and `pg-b`, `createdb shop`, load it with `psql -d shop`, then run `join-aliases.sql`, which is plain SQL, 100 times in one `psql` session.
- Wait 2 minutes for QAN. The rows below search the last 12 hours, so the workload runs again before a run of the matrix that starts later than that.

pmm-agent takes PostgreSQL's queryid from `pgsm_query_id` (`agent/agents/postgres/pgstatmonitor/pgstatmonitor_models.go:180-181`) [V], which pg_stat_monitor computes from the normalized query text, so it is the same on both servers [I]. MySQL's digest is the same on both servers for the same schema and statement [I, as plan 04]. The test's setup asserts both.

**The matrix.** `All` is the set of service names that `pmm_inventory` returns to the package's `admin` (from `-pmm.server-url`), who holds PMM's default `Full access` role. It holds `mysql-a`, `mysql-b`, `pg-a`, `pg-b`, `pmm-server-postgresql` and the live-check environment's services. For a setup, `A` is the set the caller may see, and `H = All − A` the hidden set. `Q_mysql` and `Q_pg` are the join's queryids, and `id(s)` is a service's ID from the inventory API, read as the package's `admin`.

| Setup | Access Roles | `A` |
|---|---|---|
| `one` | one Access Role, `{service_name="mysql-a"}`, assigned | `{mysql-a}` |
| `two` | two Access Roles, `{service_name="mysql-a"}` and `{service_name="pg-a"}`, assigned | `{mysql-a, pg-a}` |
| `negative` | one Access Role, `{service_name!~"mysql-b\|pg-b"}`, assigned | `All − {mysql-b, pg-b}` |
| `default` | `one`'s Access Role set as the default, nothing assigned; the callers are created after it is set | `{mysql-a}` |
| `full` (Admin only) | only PMM's default `Full access` role, which has no filter (`managed/models/database.go:857`) [V] | `All` |
| `off` | Access Control off | `All` |

Callers: an interactive Viewer and an interactive Editor (Basic, `CreateUser`), and an Admin (`CreateUser` with Grafana role `Admin`, not the package's `admin`). Each runs every setup but `full`, and the Admin runs `full`. Task 3 adds a Viewer service-account token. Each caller is new for each setup.

Expected results, for a caller under a setup. Rows of the same engine apply to `X` = MySQL and to `X` = PostgreSQL, whose services are `X-a` and `X-b`. `C = {X-a, X-b} ∩ A` are the candidates.

| Tool | Call | Expected |
|---|---|---|
| `pmm_version` | none | text starts with `PMM Server 3.` |
| `pmm_catalog` | `kind: qan_columns`; `kind: metrics, engine: mysql` | structured content equal to the package's `admin`'s |
| `pmm_inventory` | `limit: 200` | the set of `services[].service_name` is `A`; `mysql-a`'s row, when `mysql-a ∈ A`, carries its `node_name` |
| `pmm_top_queries` | `group_by: service_name, period_from: now-12h, limit: 100` | every dimension is in `A`; `{mysql-a, pg-a} ∩ A` are among them |
|  | `service_name: s`, for each `s ∈ {mysql-b, pg-b} ∩ H` | no rows, and not an error |
| `pmm_query_detail` | `queryid: Q_X, period_from: now-12h` | `C` empty: `not_found` naming the window; one: that service's `service_name`, and a `query_ref.service_id`, when set, of `id(X-a)`; two: not an error |
|  | `queryid: Q_X, service_id: id(X-b), period_from: now-12h`, `X-b ∈ H` | `not_found`, the text `errNotInList` gives for the 12-hour window, without the ID |
| `pmm_get_explain` | `queryid: Q_X, period_from: now-12h` | `C` empty: `not_found`, "the query was not seen on any of your services in …"; one: MySQL a live plan, header `EXPLAIN (json, mysql mysql-a)`, PostgreSQL `pg-a`'s stored plan (`Stored plan (pg_stat_monitor`), and `query_ref.service_id` = `id(X-a)`; two: `invalid_input` listing `X-a (id(X-a))` and `X-b (id(X-b))` |
|  | `queryid: Q_X, service_id: id(X-b), period_from: now-12h`, `X-b ∈ H` | `not_found` with the fixed text |
| `pmm_get_schema` | `queryid: Q_X, period_from: now-12h` | as `pmm_get_explain` for `C`; one: one table block each for `orders` and `customers` |
|  | `service_id: id(X-b), database: shop, tables: [orders]`, `X-b ∈ H` | `not_found` with the fixed text and hint |
| `pmm_get_config` | `service_id: id(s)` and `service_name: s`, for `s ∈ {mysql-a, mysql-b, pg-a, pg-b}` | `s ∈ A`: variables, `service_name` `s`; `s ∈ H`: `not_found` with the fixed text and hint |
| `pmm_service_health` | `service_id: id(s)`, for `s ∈ {mysql-a, mysql-b}` | `s ∈ A`: at least one MySQL signal with `last_at`; under `one`, `two` and `default` the node signals are `no_data`, with the node note; `s ∈ H`: `not_found` with the fixed text and hint |
| `pmm_query_metrics` | `query: count by (service_name) (up)` | the `service_name`s across `series[].labels` and `shared_labels` are `A` |
|  | `query: mysql_up{service_name="mysql-b"}`, `mysql-b ∈ H` | `total_series` 0, not an error |
| `pmm_list_metrics` | `kind: values, label: service_name` | `values` is `A` |
|  | `kind: series, match: [mysql_up{service_name="mysql-b"}]`, `mysql-b ∈ H` | no series |

- Under `off` and `full`, `C` has two services for each engine, so the same rows prove that the queryid is shared.
- In every run with `H` not empty, no response's text, structured content or `_meta` contains the name or the ID of a service in `H ∩ {mysql-b, pg-b}`.
- Every caller but the Admin gets HTTP 403 from `GET /v1/inventory/services` (Task 2); the Admin gets 200.
- The matrix's tool names equal `tools/list`'s, so a new tool can't skip it; plan 07 adds `pmm_alerts`.

- [ ] **Step 1: Write the helpers** in `api-tests/accesscontrol_helpers.go`, `connectWith`, and the flag and client in `init.go`.
- [ ] **Step 2: Write `TestAccessRoleMatrix`** in `access_roles_test.go`, the matrix above as a table test over setup × caller, with subtests named `<setup>/<caller>`. Its setup:
  - finds `Q_mysql` and `Q_pg` as the package's `admin`, from `pmm_top_queries` with `service_name` `mysql-a` and then `mysql-b` (and `pg-a`, `pg-b`), `search: customers`, `period_from: now-12h`: the row whose fingerprint joins `orders` and `customers`;
  - fails, not skips, unless the same queryid is found on both services of each engine;
  - calls `waitForServiceList` for each caller before its rows.
- [ ] **Step 3: Compile.** `go vet ./api-tests/...`
- [ ] **Step 4: Set up the environment** on a VM running a Feature Build of `PMM-15790-metrics-tools` (plan 05, without this plan).
- [ ] **Step 5: Run, see FAIL.**

  ```bash
  go test ./api-tests/mcp/ -run TestAccessRoleMatrix -v -count=1 -timeout 60m \
    -pmm.server-url=https://admin:<password>@<server>/ -pmm.server-insecure-tls -pmm.run-mcp-access-role-tests
  ```

  Expected: `pmm_inventory` returns `All` to a restricted Viewer, and `GET /v1/inventory/services` answers a Viewer with 200.
- [ ] **Step 6: Upgrade the server** to a Feature Build of this branch (Tasks 1 and 2), keeping its data volume, and run again: PASS. When the PostgreSQL stored-plan rows pass, delete the limitation "PostgreSQL stored plans are not yet scoped to a service" from `mcp.md` (`:386`). If they fail, keep it, and record the failure on PMM-15531 for plan 08's release gate.
- [ ] **Step 7: Record** the results, setup by setup, on PMM-15531.
- [ ] **Step 8: Commit** `PMM-15531 Test the MCP tools under Access Roles`.
- [ ] **Step 9: Run the pre-push checks** and push. The api-tests are vetted; they ran in Steps 5 and 6.

### Task 5: Land PR 1

**Files:** whatever the merge touches.

**Interfaces:** none.

- [ ] **Step 1: Wait for #6291** to merge into `PMM-MCP-GA`. Until then, open PR 1 as a draft against `PMM-15790-metrics-tools`, and continue with Step 2 when it merges.
- [ ] **Step 2: Merge `origin/PMM-MCP-GA`,** with `PMM-MCP-GA` behind 0 (00). #6291 is squash-merged, so files that this branch and plan 05 both changed conflict. Resolve them so:
  - `git diff --stat origin/PMM-15790-metrics-tools origin/PMM-MCP-GA` lists what `PMM-MCP-GA` holds beyond plan 05's tip;
  - a conflicted file not in that list takes this branch's side (`git checkout --ours -- <file>`);
  - a conflicted file in that list takes this branch's side plus that diff, by hand;
  - generated files and the golden file are regenerated as 00 says.
- [ ] **Step 3: Run the CI "Checks" sequence** (00): `make gen`, `make release`, `make format`, `go mod tidy`, then `git diff --exit-code`. Run the pre-push checks with `<base>` `origin/PMM-MCP-GA`; commit `PMM-15531 Merge PMM-MCP-GA`; push.
- [ ] **Step 4: Run a Feature Build** from the branch and verify on it, recording the evidence on PMM-15531:
  - `go test ./api-tests/mcp/ -v` as 00 gives it, and `TestAccessRoleMatrix` on Task 4's environment, its server upgraded to this build;
  - the triage with a Viewer service-account token (00); `POST /mcp` answers 404 with the endpoint off;
  - **up=0:** with a client node's `mysqld_exporter` frozen (`pkill -STOP mysqld_exporter` in the pmm-client container) for 3 minutes, its MySQL service stays in `pmm_inventory` with a `last_seen` under 2 minutes old: vmagent sends `up=0` for the failed scrapes [I]. Then `pkill -CONT mysqld_exporter`;
  - **no sample:** with the pmm-client container stopped, its push-mode services keep the `last_seen` from before the stop. After 65 minutes they are no longer in `pmm_inventory`, and `pmm_service_health` for one of them answers `not_found` naming the last hour; with `period_from: now-2h` it still answers. Started again, they are back within 2 minutes;
  - **labels:** a service registered with `--environment=mcp-env --cluster=mcp-cluster` shows both in `pmm_inventory`; one registered without them shows neither.
- [ ] **Step 5: Open PR 1** into `PMM-MCP-GA` ([00](00-roadmap.md#branch-and-pr-rules)): `PMM-15531 Build the MCP service list from series`, with the Feature Build link. The description says that the service-account token rows follow in PR 2, after PMM-15534.

### Task 3: Service-account tokens under Access Roles (ADR-12; PR 2, after PMM-15534)

PMM-15534 lands on `main` through its own ticket and PR, not through this plan. It carries ADR-12's rules: a principal whose identity lookup yields no positive user ID is refused with 401, and Access Role filters are skipped only for the anonymous identity. That PR also carries the access-control docs for assigning Access Roles to a service account (`POST /v1/accesscontrol/roles:assign`) and its release-note line that tokens start on the default Access Role. `mcp.md` exists only on `PMM-MCP-GA`, so this task points it to those docs.

**Files:**
- Modify: `api-tests/accesscontrol_helpers.go`, `api-tests/mcp/access_roles_test.go`, `documentation/docs/api/mcp.md` (the note at `:13-14`)

**Interfaces:**
- Produces: `CreateServiceAccountToken(t *testing.T, name, grafanaRole string) (userID int64, token string)` in package `apitests`, as `api-tests/server/auth_test.go:421-506` does: `POST /graph/api/serviceaccounts`, `PATCH` its `orgId` to 1, `POST .../tokens`. The account's `id` is its user ID (ADR-12). It deletes the service account.
- `TestAccessRoleMatrix` gains the caller `token`: a Viewer service account's token, sent as `Authorization: Bearer <token>`, under every setup but `full`, with the Viewer's expectations.

- [ ] **Step 1: Cut the branch.** Once PMM-15534 is merged on `main` and PR 1 on `PMM-MCP-GA`, merge `main` into `PMM-MCP-GA` under the roadmap's rules (00), then cut `PMM-15531-service-account-roles` from it.
- [ ] **Step 2: Add the helper and the `token` caller.** For `default`, the account and its token are created after the default Access Role is set; `AssignRoles` takes the account's user ID.
- [ ] **Step 3: Run the `token` rows, see FAIL,** on Task 5's Feature Build and environment (PR 1, without PMM-15534): the token sees `All` under `one`.
- [ ] **Step 4: Run the matrix on a Feature Build of this branch, see PASS.**
- [ ] **Step 5: Verify live** on that build, with Access Control on, and record the evidence on PMM-15531:
  - a Viewer service-account token whose account holds an Access Role allowing one service gets only that service from `pmm_inventory` and `pmm_top_queries`, and only its `up` series from the datasource proxy;
  - a new token whose account holds no Access Role gets the default Access Role's filter;
  - with a restricted default Access Role, a registered node's own account still lists, removes and unregisters its services with `pmm-admin`, and `pmm-agent setup` finds its node. PMM-15534's PR tests this on `main`; this repeats it after the merge (ADR-12).
- [ ] **Step 6: Update `mcp.md`.** Drop the note that Access Roles don't apply to service-account tokens (`:13-14`), and link the access-control docs that PMM-15534 adds for service accounts [I: their path].
- [ ] **Step 7: Commit** `PMM-15531 Test MCP tokens under Access Roles`.
- [ ] **Step 8: Run the pre-push checks** with `<base>` `origin/PMM-MCP-GA`, and push.
- [ ] **Step 9: Open PR 2** into `PMM-MCP-GA` ([00](00-roadmap.md#branch-and-pr-rules)): merge `origin/PMM-MCP-GA` (behind 0), run a Feature Build, run the api-tests and the triage on it, and open `PMM-15531 Test MCP tokens under Access Roles` with the Feature Build link.

## Decisions

No question is open.

- **The look-back follows the call's window** (user decision, 2026-11-09). A call with a window reads the `up` series of that window, ending at its end, and at most its last 7 days; a longer window reads its last 7 days, and a `not_found` says so. A call without a window reads the last hour. Spec §8 holds the value and ADR-08's decision points there, so ADR-08 doesn't change. It answers the question this plan raised: with a one-hour list, a service silent for more than an hour was `not_found` even for a window in which it was alive.

Settled here, with the reason:
- **`pmm_get_config`'s list covers the hour before `at`.** It reads one instant, not a window; the hour before `at` is what its QAN link covers, and with the default `at` it is the last hour.
- **Nodes** move to plan 07 (Global Constraints).
- **`pmm_service_health` for another service type** answers `invalid_input` (Global Constraints).
- **Two services with one name** within the look-back: lookups by name take the one with the newest `last_seen`. The older one is the removed service, and list order can't decide it, because the two can have different engines.
- **A large fleet:** a list row is about 300 bytes [I], so the 4 MiB read cap holds about 14,000 rows over the look-back (Global Constraints). Above that, every tool answers `pmm_unavailable`. PMM's sizing guide calls 200 nodes and up a large deployment, and a fleet near 14,000 services is not expected [I], so there is no paging of the list.
- **Caps per principal** (spec §13, "revisit with plan 06"): unchanged, per caller key. Even with PMM-15534, MCP never learns the principal's user ID: `auth_request` resolves it, and MCP authorizes nothing itself (ADR-03). The per-replica and per-service caps still bound the total.
- **The matrix's Admin** is an org Admin created for the test. PMM filters Grafana server admins the same way, by user ID (Review Focus), and changing the package's `admin` would touch every other api-test.
- **PostgreSQL stored plans** are asserted like the other rows: the qan-api2 fix is in this branch (Review Focus). PMM-15697's Jira status was not checked [I].
