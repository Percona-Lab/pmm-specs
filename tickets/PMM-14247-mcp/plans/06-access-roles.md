# Plan 06: Service list and Access Roles (task level)

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans).

**Goal:** Every service lookup in MCP uses the caller's service list, built from the metric series the caller can read, so MCP's results follow the caller's Access Roles (ADR-08, ADR-03). The Viewer inventory rules from #5942 are removed. Once PMM-15534 is merged in from `main`, service-account tokens are governed by Access Roles too (ADR-12), and an api-test matrix proves it for every MCP tool.

**Architecture:** `listServices` stops calling the inventory API. It runs one instant query through the Grafana datasource proxy (ADR-09), which vmproxy filters by the caller's Access Roles, and builds one row per `service_id` from the `up` series of the last hour. `pmm_inventory`, `engineOf`, `serviceEngine`, the resolve-first candidates and the `pmm_query_detail` narrowing (plan 04) all read that list. pmm-managed's APIs, nginx, the gRPC gateway and `lbacPrefixes` don't change: ADR-16 is deferred.

**Tech Stack:** Go 1.27, go-sdk v1.8.0, MetricsQL through the datasource proxy (VictoriaMetrics v1.154.0 behind vmproxy), api-tests.

**Spec:** [ADR-08](../adr/ADR-08-inventory-under-access-roles.md), [ADR-12](../adr/ADR-12-service-accounts-as-principals.md), [ADR-03](../adr/ADR-03-api-only-data-path.md), [spec §9](../spec.md#9-phase-4-identity-and-access-roles). Ticket PMM-15531. PMM-15534 is its own ticket on `main`.

## Global Constraints

- Needs plan 03 (`addTool`, `serviceRow`, the golden `tools/list` test) and the design review (00). Task 3 needs PMM-15534 merged on `main`. Task 4 needs plans 04 and 05 merged into `PMM-MCP-GA`: its query rows test plan 04's narrowing, and its metrics rows test plan 05's tools.
- Branch `PMM-15531-service-list`, cut from `PMM-MCP-GA`; one PR into it, opened after Task 4 (00). If PMM-15534 is not on `main` when Tasks 1, 2 and 4 are done, that PR carries Tasks 1, 2 and 4 without the service-account token rows; Task 3 and the token rows follow in a second PR.
- **The caller's service list:** built from every `up` series of the last hour, of any `service_type`, read through the datasource proxy with the caller's credentials:
  - every series with a `service_id` is a service: one row per `service_id`, with `service_name`, engine (its `service_type`), `node_id`, `node_name`, `environment`, `cluster` and `last_seen` (the newest sample time);
  - every distinct `node_id` and `node_name` across all series, node_exporter's `up` included, is a node of the list, so a host with no service on it is a node too;
  - only `service_id` is required. The other labels are optional: PMM removes empty labels before they reach a scrape target (`prepareLabels`, `managed/models/models.go:105-125`), so a service without `environment` or `cluster` has series without them;
  - no address and no port.
- Any `up` value counts. A target scraped with `up=0` stays listed with a current `last_seen`, because the service exists. A service leaves the list only when no `up` sample at all arrived in the last hour, for example when its pmm-agent or vmagent stopped.
- The list is built per tool call with the caller's own credentials, never cached or shared between callers (ADR-03). A failing list query fails the tool call; it never falls back to an unfiltered source.
- The list query goes through `QueryInstant`, so it takes a slot of plan 05's limit on requests to VictoriaMetrics, and its response is read within plan 05's size cap. If this plan lands first, plan 05 Task 1 covers it when it wraps `QueryInstant`.
- After Task 1, no MCP tool calls `/v1/inventory/`. After Task 2, `GET /v1/inventory/services` and `/nodes` are Admin-only again.
- A `service_id` or service name outside the list answers `not_found` with the fixed text "not in your service list (services that sent metrics in the last hour)", plus the tool's existing hint. A `not_found` message never echoes the ID or name the caller sent, and no error text, hint or candidate list names a service outside the list.
- Tools that need an engine (`pmm_get_explain`, `pmm_get_schema`, `pmm_get_config`) still accept only MySQL, PostgreSQL and MongoDB, with their existing `invalid_input` for another `service_type`.
- pmm-managed's APIs, nginx, the gRPC gateway and `lbacPrefixes` are unchanged.

## Review Focus

- **A service with no `up` sample at all,** for example in push mode with its pmm-agent or vmagent stopped, stays listed with its old `last_seen` for one hour, then disappears (ADR-08). A target that is scraped but down (`up=0`), such as an unreachable pull-mode target, stays listed with a current `last_seen`. A service or node renamed within the hour gives one row, with the newest labels (Task 1).
- **A service without `environment` or `cluster`,** the default, is listed like any other (Task 1).
- **A restricted Admin:** vmproxy filters an Admin's metrics by Access Role like anyone else's, so an Admin with a restricted Access Role gets a filtered list too (Task 4).
- **Service-account tokens before PMM-15534 is merged in** see every service; Task 3 is the gate, and plan 08 checks it before the merge back.
- **One `queryid` recorded on an allowed and on a hidden service:** `pmm_query_detail`, `pmm_get_explain` and `pmm_get_schema` return the allowed one or `not_found`, never the hidden one's data or name; for PostgreSQL stored plans, once PMM-15697 is fixed (Task 4).

---

### Task 1: The caller's service list from series (ADR-08)

**Files:**
- Modify: `managed/services/mcp/tools_inventory.go` (`serviceInfo`, `listServices` `:146`, `inventory`; delete `nodeNames`), `tools_qan.go` (`serviceEngine` `:605`, `engineOf` `:678`), `tools_config.go` (`service_name` lookup), `links.go` (`serviceURL`), `deps.go` and `client.go` (drop `ListServices`, `ListNodes`), `mock_pmm_api_test.go`, `helpers_test.go` (routes by query text), `testdata/tools_list.golden.json`, `documentation/docs/api/mcp.md`
- Test data: new `testdata/vm_up_services.json`; remove `services.json`, `services_with_mongo.json`, `nodes.json`
- Test: `tools_inventory_test.go`, `hardening_test.go` (config tests live there, next to `TestConfigAcceptsServiceID`), `tools_qan_test.go`, plan 04's `resolve_test.go`, `api-tests/mcp/mcp_test.go` (`TestInventory`)

**Interfaces:**
- `type serviceInfo struct { ServiceID, ServiceName, Engine, Version, NodeID, NodeName, Environment, Cluster string; LastSeen time.Time }`; `type nodeInfo struct { NodeID, NodeName string }`.
- `const serviceListQuery`, sent as an instant query:
  `max by (service_id, service_name, service_type, node_id, node_name, environment, cluster) (tlast_over_time(up[1h]))`.
  The value is the newest sample time in Unix seconds (MetricsQL `tlast_over_time`); it counts every sample, whatever its value.
- `func (s *Service) listServices(ctx context.Context, auth callerAuth) ([]serviceInfo, []nodeInfo, error)`: runs `serviceListQuery` with `queryMetrics`. It calls `func (s *Service) listServicesOver(ctx context.Context, auth callerAuth, lookback time.Duration) ([]serviceInfo, []nodeInfo, error)` with `serviceListLookback = time.Hour`; `listServicesOver` puts its look-back in the query's window. Plan 07 calls it with `alertListLookback = 7 * day` for `pmm_alerts` (ADR-17).
  - Services: each series with a non-empty `service_id`; one row per `service_id`, from the series with the newest `LastSeen`; a missing optional label is an empty field. Sorted by engine, then name, as today.
  - Nodes: every distinct `node_id` (or `node_name` when the series has no `node_id`) across all series, with or without `service_id`.
  - No version lookups: `Version` stays empty here. The `withNodeNames` argument goes.
- `pmm_inventory` is the only caller of `enrichVersions`, which keeps its three engines; another `service_type` reports `unknown`. Its `engine` filter and its rows apply after the query: it lists every service in the list, of any `service_type`, and `engine` matches `service_type` exactly. `engine` must be one of PMM's service types (`mysql`, `postgresql`, `mongodb`, `proxysql`, `haproxy`, `valkey`, `external`; `managed/models/service_model.go:42-48`), else `invalid_input` as today.
- `engineOf` answers `not_found` with the fixed text and its hint: "not in your service list (services that sent metrics in the last hour); use pmm_inventory to list service ids".
- `pmm_get_config` with `service_name` and no `service_id` resolves the name through the list, like `engineOf` does for IDs; a name outside the list is `not_found` with the same fixed text. The engine comes from the list unless the caller gives one.
- `serviceRow` (plan 03) becomes `service_id`, `service_name`, `engine`, `version`, `node_id`, `node_name`, `environment`, `cluster`, `last_seen`, `pmm_url`. `address` and `port` are removed. `service_name`, `version`, `node_name`, `environment` and `cluster` are marked Untrusted, as `tool-contract.md` §7 lists: `TestUntrustedFieldsMarked` gains `environment` and `cluster` and loses `address`. `serviceURL` also covers `proxysql` and `haproxy` (`proxysql-instance-summary`, `haproxy-instance-summary`); for another `service_type`, `pmm_url` is omitted.
- `fakePMM`: a route key may end in ` ?<text>`. It matches a request with that method and path whose `query` parameter contains `<text>`, and wins over the plain key; the longest matching text wins. Plan 05 Task 1 routes its fixtures the same way; whichever plan lands first adds it.

**Steps:**
- Write the tests first:
  - `TestServiceList`, against one fixture:
    - the query sent, verbatim, to `/graph/api/datasources/proxy/uid/<uid>/api/v1/query` with the caller's `Authorization`;
    - two series for one `service_id` under two `node_name` values give one row with the newer labels;
    - a series without `environment` and `cluster` gives a row with both empty;
    - a node_exporter series (node labels only) gives a node and no service;
    - a `proxysql` series gives a service with engine `proxysql`;
    - a pull-mode target whose last sample is `up=0` is listed, with that sample's time as `last_seen`;
    - `LastSeen` comes from the value; a 401 from the proxy is `unauthorized`, not an empty list;
    - no version query is sent.
  - `TestInventoryTool`: rows carry `last_seen` and no `address`; with no series, the text says "No monitored services sent metrics in the last hour."; the `engine` filter matches `service_type`, `proxysql` included; the `node` filter works as today; each engine's version comes from its own fixture, now that queries are routed by text.
  - `TestEngineOfOutsideList`: a `service_id` absent from the series is `not_found` with the fixed text, and the message contains neither that ID nor any other service's name or ID.
  - `TestConfigByServiceName`: a name in the list returns its variables; a name outside it is `not_found` with the fixed text, without the name, and sends no metrics query.
- Implement. Remove `ListServices` and `ListNodes` from `pmmAPI` and `client`, then regenerate the mock with `go tool mockery --config .mockery.yaml` and commit only `managed/services/mcp/mock_pmm_api_test.go`.
- Move every test that routes `GET /v1/inventory/services` or `/nodes` to the series fixture, including those of plans 04 and 05 already merged. No test records a `/v1/inventory/` request.
- The `pmm_inventory` description says the list holds the services that sent metrics in the last hour. Regenerate the golden file (`-update`).
- api-test `TestInventory`: compare with what `serviceListQuery` returns to the admin through the datasource proxy, not with the inventory API; no row contains `address=`.
- `mcp.md`: `pmm_inventory`'s fields and backing API; the one-hour rule; the `pmm_get_explain` and `pmm_get_config` rows lose `GET /v1/inventory/services`.
- On the live-check environment (00), with at least 50 services: time `serviceListQuery` with `[1h]`, `[24h]` and `[7d]`, 20 runs each, and record the p50 and p95 on PMM-15531 and in ADR-08's Consequences. The look-backs stay 1 h for every tool and 7 days for `pmm_alerts` (ADR-17) unless a pmm-specs PR changes them.
- Run `go test ./managed/services/mcp/...` and the lint (00). Commit `PMM-15531 Build the MCP service list from Access-Role-filtered series`.

### Task 2: Remove the Viewer inventory rules

**Files:**
- Modify: `managed/services/grafana/auth_server.go` (`methodRules`, the comment and two entries at `:160-167` on `PMM-MCP-GA`), `documentation/docs/api/mcp.md` (the authorization table)
- Test: `managed/services/grafana/auth_server_test.go` (`TestResolveRule`, `:127-138`)

**Interfaces:** none.

**Steps:**
- In `TestResolveRule`, `GET /v1/inventory/services`, `/v1/inventory/services/svc-1` and `/v1/inventory/nodes` expect `admin`; `/v1/inventory/services:getTypes` stays `viewer`. Run, see FAIL.
- Delete the two entries and their comment. Run `go test ./managed/services/grafana/...`, see PASS.
- `mcp.md`: `pmm_inventory` needs a Viewer token and reads no inventory API.
- Commit `PMM-15531 Keep inventory reads Admin-only`.

### Task 3: Service-account tokens under Access Roles (ADR-12)

PMM-15534 lands on `main` through its own ticket and PR, not through this plan. That PR also carries the access-control docs for assigning Access Roles to a service account (`POST /v1/accesscontrol/roles:assign`) and its release-note line that tokens start on the default Access Role. `mcp.md` exists only on `PMM-MCP-GA`, so this task points it to those docs.

**Files:**
- Modify: `documentation/docs/api/mcp.md`

**Interfaces:** none.

**Steps:**
- Once PMM-15534 is merged on `main`, merge `main` into `PMM-MCP-GA` under the roadmap's rules (00), then `PMM-MCP-GA` into this branch.
- On the live-check environment (00), with Access Control on:
  - a Viewer service-account token whose account holds an Access Role allowing one service gets only that service from `pmm_inventory` and `pmm_top_queries`, and only its `up` series from the datasource proxy;
  - a new token whose account holds no Access Role gets the default Access Role's filter;
  - with a restricted default Access Role, a registered node's own account still lists, removes and unregisters its services with `pmm-admin`, and `pmm-agent setup` finds its node (PMM-15534's PR tests this on `main`; this repeats it after the merge).
  Record the evidence on PMM-15531.
- `mcp.md`: drop the note that Access Roles don't apply to service-account tokens; link the access-control docs.
- Commit `PMM-15531 Point MCP docs to Access Roles for service accounts`.

### Task 4: Access Role matrix for the MCP tools (api-tests)

**Files:**
- Create: `api-tests/mcp/access_roles_test.go`; `api-tests/accesscontrol_helpers.go` (package `apitests`, imported as `pmmapitests`)
- Modify: `api-tests/mcp/mcp_test.go` (`connectWith`)

**Interfaces:**
- `func connectWith(t *testing.T, authorization string) *mcp.ClientSession`: a session with a given `Authorization` header (a Bearer token or basic auth).
- Helpers in package `apitests`, modelled on the unexported ones in `api-tests/accesscontrol/accesscontrol_test.go`. That package keeps its own `TestMain` setup and is not switched. Each helper fails the test on error and registers its undo with `t.Cleanup`:
  - `SetAccessControl(t *testing.T, enabled bool)`: restores the previous setting;
  - `CreateRole(t *testing.T, title, filter string) int64`: deletes the Access Role;
  - `AssignRoles(t *testing.T, userID int64, roleIDs ...int64)`;
  - `SetDefaultRole(t *testing.T, roleID int64)`: restores the previous default Access Role;
  - `CreateUser(t *testing.T, login, password, grafanaRole string) int64`: deletes the Grafana user;
  - `CreateServiceAccountToken(t *testing.T, name, grafanaRole string) (userID int64, token string)`: deletes the service account;
  - `WaitForFilters(t *testing.T, authorization string, wantServices ...string)`: pmm-managed caches the Access Control setting for a few seconds, so this polls `max by (service_name) (up)` through the datasource proxy with `authorization`, once a second for up to 20 s, until the set of `service_name` values equals `wantServices`. On timeout it logs the last set with `t.Logf` and returns, so the assertions report what the server does.

**Environment:** the live-check environment (00), plus a second MySQL and a second PostgreSQL service on the same node as the first ones, initialised from the same image and script. A workload runs the same statements on both services of each engine, so the same `queryid` is recorded on both [I]. Setup asserts, as the Admin, that such a `queryid` is in QAN for both services of each engine, and fails otherwise. Below, `mysql-a` and `pg-a` are allowed, `mysql-b` and `pg-b` hidden.

**Steps:**
- Write the helpers.
- Write the matrix as a table test over caller × Access Role setup:
  - Callers: an interactive Viewer and an interactive Editor (basic auth), a Viewer service-account token, an Admin.
  - Access Role setups:
    - `one`: one Access Role, `{service_name="mysql-a"}`;
    - `two`: two Access Roles, `{service_name="mysql-a"}` and `{service_name="pg-a"}`;
    - `negative`: one Access Role, `{service_name!~"mysql-b|pg-b"}`;
    - `default`: `one`'s Access Role set as the default Access Role, nothing assigned;
    - `none`: no Access Role (Admin only);
    - `off`: Access Control off.
- Expected under `two`:

  | Tool | Result | With a hidden service's `service_id` or name |
  |---|---|---|
  | `pmm_inventory` | `mysql-a`, `pg-a` and their node | — |
  | `pmm_top_queries` | rows of the allowed services only | no rows |
  | `pmm_query_detail` on the shared `queryid` | the allowed service's detail | `not_found` |
  | `pmm_get_explain` on the shared `queryid` | MySQL: a live plan from `mysql-a`; PostgreSQL: `pg-a`'s stored plan | `not_found` |
  | `pmm_get_schema` on the shared `queryid` | the allowed service's tables | `not_found` |
  | `pmm_get_config` | the allowed service's variables | `not_found` |
  | `pmm_query_metrics`, `pmm_list_metrics` | the allowed services' series, names and label values | none |
  | `pmm_service_health` | the allowed service's signals | `not_found` |

- The other setups: `one` and `default` give `mysql-a` only; `negative` gives the same as `two`; `off`, and an Admin under `none`, give every service; an Admin under `one` gets `mysql-a` only, as metrics are filtered for Admins too.
- The PostgreSQL stored-plan row holds once PMM-15697 is fixed (spec §9.4). Until then, a failure of that row alone is recorded on PMM-15531 for the release gate (plan 08), not fixed here.
- In every restricted run, no response text or `_meta` contains `mysql-b`, `pg-b` or their `service_id`. A Viewer's `GET /v1/inventory/services` answers 403.
- If Task 3 is not done yet (PMM-15534 not on `main`), the service-account token rows are left out and added with Task 3's PR (Global Constraints).
- Run the package on a Feature Build of the branch; record the results on PMM-15531.
- Commit `PMM-15531 Test the MCP tools under Access Roles`.

### Task 5: Land

**Files:** none.

**Interfaces:** none.

**Steps:**
- The last step of the plan (00): merge `origin/PMM-MCP-GA` into the branch, with `PMM-MCP-GA` behind 0; run a Feature Build from the branch, verify live, and open the PR `PMM-15531 Build the MCP service list from Access-Role-filtered series` into `PMM-MCP-GA`.
