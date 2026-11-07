# Plan 07: Alerts (task level)

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans).

**Goal:** `pmm_alerts` returns the caller's firing alerts from Grafana's folder-scoped rules API, narrowed by MCP to the caller's service list (plan 06). `pmm_advisors` is out of the Tech Preview ([ADR-18](../adr/ADR-18-advisors.md)); this plan doesn't build it.

**Architecture:** The tool reads Grafana's rules API through nginx on loopback with the caller's credentials, like every other tool (ADR-03). That API is folder-scoped, so the tool shows a Viewer what PMM's own alert page shows; Grafana's alert list endpoints are not, and never supply the list. Silence state comes from the Alertmanager, joined by rule UID only. MCP then keeps the alerts that belong to the caller's service list, filters, sorts and pages them, and returns plan 03's typed results. No new pmm-managed API, no `lbacPrefixes` change, no Grafana fork change.

**Tech Stack:** Go 1.27, go-sdk v1.8.0, Grafana's alerting HTTP API (the Prometheus-style rules API and the Alertmanager API).

**Spec:** [ADR-17](../adr/ADR-17-alerts.md), [ADR-18](../adr/ADR-18-advisors.md), [ADR-03](../adr/ADR-03-api-only-data-path.md), [ADR-11](../adr/ADR-11-output-contract.md), [spec §7.2, §7.3](../spec.md#72-alerts). Ticket PMM-15790.

## Global Constraints

- Needs plan 06 (`listServices`), which needs plan 03, and the design review (00). Branch `PMM-15790-alerts`, cut from `PMM-MCP-GA`; one PR into it, opened after Task 5 (00).
- **MCP's narrowing here is consistency, not a security boundary.** Grafana's alerting APIs don't apply Access Roles. The same caller reads them unfiltered by Access Roles with the same credentials, and in the PMM UI. Tests, docs and tool descriptions never call the narrowing a restriction. Applying Access Roles to them is ADR-16's work, which is deferred.
- **The caller's service list `L`** is plan 06's list: services of every `service_type` (ProxySQL, HAProxy and the rest included) and every node in it, hosts with only node_exporter included. Plan 06 builds the services only (its Global Constraints); Task 2 adds the nodes and the look-back. For `pmm_alerts`, `L` is `listServicesOver(ctx, auth, alertListLookback)`, 7 days (ADR-17). Its query takes a slot of plan 05's limit on requests to VictoriaMetrics, like every request MCP sends there.
- **Alert narrowing** (ADR-17), against `L`:
  - only four labels count, each checked against one set of `L`: `service_id` against the service IDs, `service_name` against the service names, `node_id` against the node IDs, `node_name` against the node names;
  - an alert of PMM's own rules is shown whatever it names: those are PMM's HA and PMM Server component rules, whose `node_id`, `node_name` and `service_name` name PMM Server replicas and components, never in `L` (ADR-17). They are identified by rule UID or provenance, as Task 1 records, never by a label;
  - an alert that carries `service_id` or `service_name` is kept only if each service label it carries is in its set; its node labels are not checked, because PMM's `*_down` templates name the node the exporter's pmm-agent runs on (`pmm-server` for RDS and Azure services), not the service's node (ADR-17);
  - an alert that carries no service label but `node_id` or `node_name` is kept only if each node label it carries is in its set;
  - an alert that carries none of them is shown, as Grafana's UI shows it to the same caller;
  - annotations and labels other than these four, `pmm_provisioned` included, are never used for narrowing.
- **Source of the list:** the rules API only. An Alertmanager alert adds silence state to an alert of a rule the rules API returned, joined by rule UID; it never adds an alert.
- A failing service list fails the tool call; the tool never returns un-narrowed results.
- Firing alerts only, silenced or not, with the silence's end time; current state, no history. The tool description and every result, an empty one included, carry the note "Currently firing alerts only; resolved alerts are not shown." (ADR-17). Read only: no silencing or acknowledging (ADR-05).
- Caps (spec §8): `pmm_alerts` 50/200 (default/maximum), paged with `limit` and `offset`.
- A `service_id`, `service_name` or `node_name` filter outside `L` answers `not_found` with plan 06's fixed text, "not in your service list (services that sent metrics in the last hour)", with "in the last 7 days" for `pmm_alerts`, which never echoes the value the caller sent.
- Untrusted fields: an alert's name, severity, labels, summary and description.
- Every map field in a result is `omitempty` or always non-nil (plan 03's contract rule).
- The new tool is added to `registerTools` (`mcp.go:194`) and to the expected name list in `TestInitializeAndListTools` (`mcp_test.go:51`). It regenerates `testdata/tools_list.golden.json` (`-update`), lists its Untrusted fields in `TestUntrustedFieldsMarked`, gets a case in `TestErrorsCarryNoStructuredContent`, and is added to the exemptions of `TestRedactionInBothRenderings` with the reason "returns no statement text" (plan 03 Task 8). Each new `pmmAPI` method regenerates the mock with `go tool mockery --config .mockery.yaml` and `make format`; commit only `managed/services/mcp/mock_pmm_api_test.go`.

## Review Focus

- **A server-level alert,** with no service or node label, is shown to a restricted caller, as Grafana shows it (Task 2).
- **An alert from a rule that aggregates `service_name` away but keeps `node_name`** is kept when that node is in `L`: a node with a listed service on it, or a host whose node_exporter series the caller can read. Under a negative Access Role filter such as `{service_name!="b"}`, VictoriaMetrics returns every node_exporter series, so node-only alerts of `b`'s host are kept while `b`'s own alerts are dropped (Task 2).
- **A service whose pmm-agent went silent** (push mode, pmm-agent or vmagent stopped) sends no `up` samples. A target that is scraped but down (`up=0`) still does. The silent service's alerts, the one saying it is down included, stay in `pmm_alerts` for 7 days, because alerts use the 7-day list; after that they are dropped while Grafana still shows them. Other tools drop the service after an hour (ADR-08). Task 2 pins this; `mcp.md` states it (Task 4).
- **Grafana folder permissions** that hide a rule from a Viewer also hide its alerts, before MCP's narrowing, because the list comes from the rules API (Task 1 checks it; Task 5 tests it). A silenced alert of a hidden rule adds nothing (Task 2).
- **A user's rule labelled `pmm_provisioned="1"`** is narrowed like any other rule: only PMM's own rules, by UID or provenance, are shown whatever they name (Task 2).
- **Annotation text that names another service** is returned as written and never used for narrowing (Task 2).

---

### Task 1: Check the rules API and the silence join (gates ADR-17's acceptance)

**Files:**
- Modify: pmm-specs `tickets/PMM-14247-mcp/adr/ADR-17-alerts.md`

**Interfaces:** produces the field mapping Task 2 uses: name, severity, labels, summary, description, start time, silenced, silence end, rule UID, and the field that identifies PMM's own rules.

**Steps:**
- On the live-check environment (00), set up:
  - PMM alert rules from templates in two folders, one of them without Viewer access;
  - firing alerts for two services, one node-level alert, and one with no service or node label (a rule on `vector(1)`);
  - one silenced alert.
- As a Viewer and as an Editor, call `GET /graph/api/prometheus/grafana/api/v1/rules` through nginx, and record:
  - the status code;
  - which rules and firing alerts come back: none of the folder without Viewer access for the Viewer;
  - whether each alert carries the labels `service_name`, `node_name`, `severity`, `alertname`, and its rule's UID;
  - which field identifies PMM's own HA and PMM Server component rules: their fixed rule UIDs, or the rules' provenance.
- As the same callers, call `GET /graph/api/alertmanager/grafana/api/v2/alerts` and `GET /graph/api/alertmanager/grafana/api/v2/silences`, and record how a silenced alert carries its rule UID (the `__alert_rule_uid__` label [I]) and `silencedBy`, and where the silence's end time is.
- PMM's own alert page reads the same rules API (`ui/apps/pmm/src/api/alerting.ts`). `pmm_alerts` joins the silence state by rule UID only, and never takes an alert from the Alertmanager list.
- If the rules API shows the Viewer a rule of the folder without Viewer access, stop: ADR-17 changes through a pmm-specs PR before Task 2.
- Record the field mapping and the evidence in ADR-17 through a pmm-specs PR `PMM-15790 Record the Grafana rules API for MCP`. Task 2 starts after it is merged.

### Task 2: `pmm_alerts`

**Files:**
- Create: `managed/services/mcp/tools_alerts.go`, `tools_alerts_test.go`, `testdata/alerts_*.json`
- Modify: `client.go`, `deps.go` (`pmmAPI`), `mock_pmm_api_test.go`, `mcp.go` (`registerTools`), `mcp_test.go`, `contract_test.go` (`TestUntrustedFieldsMarked`), `testdata/tools_list.golden.json`

**Interfaces:**
- `pmmAPI` gains `Alerts(ctx context.Context, auth callerAuth) ([]grafanaAlert, error)`: a raw `getJSON` on `graph/api/prometheus/grafana/api/v1/rules`, one `grafanaAlert` per firing alert of the rules returned; and `SilencedAlerts` and `Silences`, raw `getJSON`s on the Alertmanager API, for silence state only.
- `type grafanaAlert struct { RuleUID string; PMMRule bool; Labels, Annotations map[string]string; StartsAt time.Time; Silenced bool; SilencedUntil *time.Time }`, filled per Task 1's mapping. `PMMRule` comes from the rule UID or provenance, never from a label. `Silenced` and `SilencedUntil` are joined by rule UID only; an Alertmanager alert whose rule UID isn't among the rules returned is ignored.
- Plan 06's `listServices(ctx, auth) ([]serviceInfo, error)` becomes a call of `func (s *Service) listServicesOver(ctx context.Context, auth callerAuth, lookback time.Duration) ([]serviceInfo, []nodeInfo, error)` with one hour, which drops the nodes. `serviceListQuery` takes the look-back as its window. `type nodeInfo struct { NodeID, NodeName string }`: one per distinct `node_id`, named as in its newest row, or per `node_name` when a row has no `node_id`, across every row of the query, with a service or not (ADR-08). `const alertListLookback = 7 * day`.
- `type serviceSet struct { serviceIDs, serviceNames, nodeIDs, nodeNames map[string]bool }`; `func newServiceSet(services []serviceInfo, nodes []nodeInfo) serviceSet`, from both results of `listServicesOver`; `func (l serviceSet) keepAlert(a grafanaAlert) bool` applies the alert narrowing rule.
- `type alertsInput struct { ServiceID, ServiceName, NodeName, Severity string; Limit, Offset int }`, every field `omitempty`.
- `type alertRow struct { Name, Severity string (both Untrusted); Labels map[string]string (Untrusted); Summary, Description string (both Untrusted); StartsAt time.Time; Silenced bool; SilencedUntil *time.Time; PMMURL string }`, snake_case JSON. `Labels` is `json:"labels,omitempty"` and leaves out labels that start with `__`. `PMMURL` is `<base>graph/alerting/grafana/<rule uid>/view`, the pattern PMM's UI uses (`AlertStatusTable.utils.ts:85`), or `<base>graph/alerting/list` when there is no rule UID.
- `type alertsResult struct { Alerts []alertRow; Page page; Note string }` with `render()`: the note, then one line per alert (severity, name, service, node, start time, silence end, link) with its summary below, then the paging marker. `Note` is always "Currently firing alerts only; resolved alerts are not shown."
- Filters are exact. `service_id`, `service_name` and `node_name` compare labels; `severity` compares the `severity` label, case-insensitively. An alert without the label never matches a filter on it.
- Order: severity `critical`, `error`, `warning`, then other values alphabetically; then `starts_at`, newest first; then name.

**Steps:**
- Write `TestKeepAlert`, a table:
  - a service in `L`: kept;
  - a node in `L`: kept;
  - a service outside `L`: dropped;
  - a service in `L` with a node outside `L`: kept, because a service alert's node labels are not checked (an RDS service's down alert with `node_name="pmm-server"`);
  - a service in `L` with a second service label outside `L` (`service_id` listed, `service_name` not): dropped;
  - for a restricted caller, PMM's own rules with `node_id` = `PMM_HA_NODE_ID` (`pmm_ha_node_unreachable` on HA), with `service_name="clickhouse"` (`pmm_clickhouse_down` on HA), and with `node_name="pmm-server"` (`pmm_grafana_down` on a standalone server): all kept;
  - a user's rule labelled `pmm_provisioned="1"` that names a service outside `L`: dropped;
  - no service or node label: shown;
  - an annotation that names a hidden service: no effect;
  - each of the four labels checked against its own set: an alert with only a `node_name` equal to a listed service's name is still dropped.
- Write `TestAlertsTool` against a fixture with alerts for allowed service A, hidden service B, A's node, a node of B only, a server-level alert and a silenced alert:
  - the result holds A's alert, the node alert of A's node, the server-level alert and the silenced alert with `silenced_until`;
  - an Alertmanager alert whose rule UID isn't in the rules API's answer adds no alert, and its silence marks nothing; an alert's silence state comes from the Alertmanager alert with its rule UID, not from matching labels;
  - the `service_name`, `node_name` and `severity` filters;
  - a `service_id` filter for B is `not_found` with the fixed text, and the message contains neither B's ID nor any other service's name or ID;
  - the order above; 120 alerts with `limit` 50 set `page.truncated`;
  - a 401 from Grafana is `unauthorized`; a failing service list fails the call;
  - an alert for a service whose last `up` sample is 3 hours old is kept, and one whose last sample is 8 days old is dropped (Review Focus);
  - every result, an empty one included, carries the note in `note` and as the text's first line;
  - two services on one node, `L` holding one of them: the other service's alerts are dropped, and the node's own alerts are kept;
  - a negative Access Role filter: with `L` as VictoriaMetrics returns it for `{service_name!="B"}` (every node_exporter series, every service but B), B's alerts are dropped and the node-only alert of B's host is kept;
  - the `mysql_down` template's labels (`service_id`, `service_name`, `node_name`, no `environment`) for a service in `L` whose pmm-agent runs on another node, so `node_name` is not in `L`, with `L` built under the role `{environment="prod"}`: kept;
  - Access Control off: with `L` holding a ProxySQL service and a node-only host, the ProxySQL alert and the node-only alert are kept.
- Run, see FAIL. Implement: `listServicesOver`, then `Alerts`, narrowing, filters, order, `paginate`, render. Add a `TestServiceList` case: the nodes of plan 06's `vm_up_list.json` are `node-1` (`demo-node`, not the older `old-node`) and `node-2` (`bare-host`), the second from a row without a service.
- Register the tool; add it to the name list, `TestErrorsCarryNoStructuredContent`, `TestEmptyAndDegradedResults` and the redaction exemptions; regenerate the golden file and the mock; list the Untrusted fields. Run `go test ./managed/services/mcp/...`, see PASS.
- Commit `PMM-15790 Add pmm_alerts`.

### Task 3: `pmm_advisors` (removed)

`pmm_advisors` is out of the Tech Preview ([ADR-18](../adr/ADR-18-advisors.md)); nothing to build. ADR-18 keeps its design for a later ticket. The task's number is kept so references to Tasks 4 and 5 stay valid.

### Task 4: `Instructions` and docs

**Files:**
- Modify: `managed/services/mcp/mcp.go` (`Instructions`), `documentation/docs/api/mcp.md`
- Test: `mcp_test.go` (`TestInitializeAndListTools`)

**Interfaces:** none.

**Steps:**
- `TestInitializeAndListTools`: the instructions contain `pmm_alerts`, and their list of untrusted text names alert summaries and descriptions. Run, see FAIL.
- Add one line to `Instructions`: "For what is wrong now, call pmm_alerts (firing alerts)." Extend the list of untrusted text in `Instructions` (plan 04) with alert names, labels, summaries and descriptions, and the links in them: output-schema marks don't reach every model (`tool-contract.md` §7). Run, see PASS.
- `mcp.md`:
  - the tool, its filters and caps; alert summaries and descriptions are returned as written (ADR-07);
  - Advisor results are not in MCP (ADR-18);
  - the list is narrowed to the caller's services to match its other results;
  - a service with no `up` sample for an hour leaves the list of the other tools, but its alerts stay in `pmm_alerts` for 7 days; after 7 days without samples they leave it too;
  - `pmm_alerts` shows currently firing alerts only; resolved alerts are not shown.
- Commit `PMM-15790 Document pmm_alerts`.

### Task 5: api-tests and the PR

**Files:**
- Create: `api-tests/mcp/alerts_test.go`, using plan 06 Task 4's helpers
- Modify: `api-tests/mcp/access_roles_test.go`: plan 06's `TestAccessRoleMatrix` requires a row for every tool in `tools/list`

**Interfaces:** none.

**Steps:**
- On the live-check environment (00), with Task 1's alert set, for two services A and B:
  - a Viewer whose Access Role allows A gets A's alert, the node alert of A's node and the server-level alert from `pmm_alerts`, and nothing of B;
  - an alert of the folder without Viewer access doesn't reach a Viewer;
  - a Viewer whose Access Role is `{service_name!="B"}` doesn't get B's alerts, and gets the node-only alerts of every host;
- Add `pmm_alerts` to `TestAccessRoleMatrix`: under every setup, no alert names a service in `H`, and with `service_name` of a service in `H ∩ {mysql-b, pg-b}` the call is `not_found` with the 7-day fixed text.
- Run plan 05's load test again (plan 05 Task 9 Step 4) with a fourth loop per caller that calls `pmm_alerts`, which reads the 7-day list. The same pass threshold applies.
- Record the results on PMM-15790.
- The last step of the plan (00): merge `origin/PMM-MCP-GA` into the branch, with `PMM-MCP-GA` behind 0; run a Feature Build from the branch, verify live, and open the PR `PMM-15790 Add pmm_alerts` into `PMM-MCP-GA`.
