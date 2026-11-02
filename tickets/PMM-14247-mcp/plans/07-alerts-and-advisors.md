# Plan 07: Alerts and Advisors (task level)

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans).

**Goal:** `pmm_alerts` returns the caller's firing alerts from Grafana's alert API, and `pmm_advisors` the caller's failed Advisor checks from `GET /v1/advisors/checks/failed`. MCP narrows both to the caller's service list (plan 06).

**Architecture:** Both tools call existing APIs through nginx on loopback with the caller's credentials, like every other tool (ADR-03): Grafana's alert API, so Grafana's folder permissions apply [I] (Task 1 settles it), and the Advisors API, at the Editor Grafana role. MCP then keeps the items that belong to the caller's service list, filters, sorts and pages them, and returns plan 03's typed results. No new pmm-managed API, no `lbacPrefixes` change, no Grafana fork change.

**Tech Stack:** Go 1.27, go-sdk v1.8.0, Grafana's alerting HTTP API, the generated `advisor_service` client (`api/advisors/v1/json/client`).

**Spec:** [ADR-17](../adr/ADR-17-alerts.md), [ADR-18](../adr/ADR-18-advisors.md), [ADR-03](../adr/ADR-03-api-only-data-path.md), [ADR-11](../adr/ADR-11-output-contract.md), [spec §7.2, §7.3](../spec.md#72-alerts). Ticket PMM-15790.

## Global Constraints

- Needs plan 06 (`listServices`), which needs plan 03, and the design review (00). Branch `PMM-15790-alerts-advisors`, cut from `PMM-MCP-GA`; one PR into it, opened after Task 5 (00).
- **MCP's narrowing here is consistency, not a security boundary.** Grafana's alert API and the Advisors API don't apply Access Roles. The same caller reads them unfiltered with the same credentials, and in the PMM UI. Tests, docs and tool descriptions never call the narrowing a restriction. Applying Access Roles to these APIs is ADR-16's work, which is deferred.
- **The caller's service list `L`** is plan 06's `listServices`: services of every `service_type` (ProxySQL, HAProxy and the rest included) and every node in it, hosts with only node_exporter included.
- **Alert narrowing** (ADR-17), against `L`:
  - only four labels count, each checked against one set of `L`: `service_id` against the service IDs, `service_name` against the service names, `node_id` against the node IDs, `node_name` against the node names;
  - an alert that carries none of them is shown, as Grafana's UI shows it to the same caller;
  - an alert that carries any of them is kept only if each one it carries is in its set; one label outside its set drops it;
  - annotations and other labels are never used for narrowing.
- **Advisor narrowing** (ADR-18): a result is kept when its `service_id` is in `L`. Counts cover kept results only.
- A failing service list fails the tool call; neither tool ever returns un-narrowed results.
- `pmm_advisors` needs the Editor Grafana role (`/v1/advisors`, `auth_server.go:84-86`). With a Viewer token the API answers 403, and the tool `unauthorized`.
- Firing alerts only, silenced or not, with the silence's end time; current state, no history. Read only: no silencing, acknowledging, running checks or changing them (ADR-05).
- Caps (spec §8): `pmm_alerts` 50/200 and `pmm_advisors` 50/200 (default/maximum), paged with `limit` and `offset`.
- A `service_id`, `service_name` or `node_name` filter outside `L` answers `not_found` with plan 06's fixed text, "not in your service list (services that sent metrics in the last hour)", which never echoes the value the caller sent.
- Untrusted fields: an alert's name, labels, summary and description; an Advisor result's summary and description.
- Every map field in a result is `omitempty` or always non-nil (plan 03's contract rule).
- Each new tool is added to `registerTools` (`mcp.go:194`) and to the expected name list in `TestInitializeAndListTools` (`mcp_test.go:51`). It regenerates `testdata/tools_list.golden.json` (`-update`), lists its Untrusted fields in `TestUntrustedFieldsMarked`, gets a case in `TestErrorsCarryNoStructuredContent`, and is added to the exemptions of `TestRedactionInBothRenderings` with the reason "returns no statement text" (plan 03 Task 8). Each new `pmmAPI` method regenerates the mock with `go tool mockery --config .mockery.yaml`; commit only `managed/services/mcp/mock_pmm_api_test.go`.

## Review Focus

- **A server-level alert,** with no service or node label, is shown to a restricted caller, as Grafana shows it (Task 2).
- **An alert from a rule that aggregates `service_name` away but keeps `node_name`** is kept when that node is in `L`: a node with a listed service on it, or a host whose node_exporter series the caller can read. Under a negative Access Role filter such as `{service_name!="b"}`, VictoriaMetrics returns every node_exporter series, so node-only alerts of `b`'s host are kept while `b`'s own alerts are dropped (Task 2).
- **A service with no `up` sample at all for an hour,** for example in push mode with its pmm-agent or vmagent stopped, leaves the list (ADR-08). A target that is scraped but down (`up=0`) stays in it. Its alerts are then dropped from `pmm_alerts`, including the one saying it is down, while Grafana still shows them. Task 2 pins this behaviour; `mcp.md` states it (Task 4).
- **Grafana folder permissions** that hide a rule from a Viewer also hide its alerts, before MCP's narrowing [I] (Task 1 records which endpoint does this, if any; Task 5 tests it).
- **Advisors disabled in settings:** `invalid_input` with a message that says so, never an empty list (Task 3).
- **Annotation text that names another service** is returned as written and never used for narrowing (Task 2).

---

### Task 1: Settle the Grafana alert endpoint (gates ADR-17's acceptance)

**Files:**
- Modify: pmm-specs `tickets/PMM-14247-mcp/adr/ADR-17-alerts.md`

**Interfaces:** produces the endpoint and the field mapping Task 2 uses: name, severity, labels, summary, description, start time, silenced, silence end, rule UID.

**Steps:**
- On the live-check environment (00), set up:
  - PMM alert rules from templates in two folders, one of them without Viewer access;
  - firing alerts for two services, one node-level alert, and one with no service or node label (a rule on `vector(1)`);
  - one silenced alert.
- As a Viewer and as an Editor, call `GET /graph/api/alertmanager/grafana/api/v2/alerts` and `GET /graph/api/prometheus/grafana/api/v1/alerts` through nginx. For each, record:
  - the status code;
  - which alerts come back, including those of the folder without Viewer access;
  - whether the labels `service_name`, `node_name`, `severity`, `alertname` and a rule UID are present;
  - whether silenced alerts and their silence end time are available. The Alertmanager alert carries `silencedBy`; the end time is in `GET /graph/api/alertmanager/grafana/api/v2/silences`.
- The PMM UI's alert page joins Grafana's rules API with the Alertmanager alerts and silences (`ui/apps/pmm/src/api/alerting.ts`). Record whether `pmm_alerts` needs the same join.
- Choose the endpoint whose answer to a Viewer is narrowed by folder permissions. If both are, choose the Alertmanager API, since it carries the silence state. If neither is, record that, and correct ADR-17's "folder permissions apply" in the same PR.
- Record the endpoint, the field mapping and the evidence in ADR-17 through a pmm-specs PR `PMM-15790 Settle the Grafana alert endpoint for MCP`. Task 2 starts after it is merged.

### Task 2: `pmm_alerts`

**Files:**
- Create: `managed/services/mcp/tools_alerts.go`, `tools_alerts_test.go`, `testdata/alerts_*.json`
- Modify: `client.go`, `deps.go` (`pmmAPI`), `mock_pmm_api_test.go`, `mcp.go` (`registerTools`), `mcp_test.go`, `contract_test.go` (`TestUntrustedFieldsMarked`), `testdata/tools_list.golden.json`

**Interfaces:**
- `pmmAPI` gains `Alerts(ctx context.Context, auth callerAuth) ([]grafanaAlert, error)`: a raw `getJSON` on Task 1's endpoint under `graph/api/`. If Task 1 needs the silences join, also `Silences(ctx context.Context, auth callerAuth) ([]grafanaSilence, error)`.
- `type grafanaAlert struct { Labels, Annotations map[string]string; StartsAt time.Time; Silenced bool; SilencedUntil *time.Time }`, filled per Task 1's mapping.
- `type serviceSet struct { serviceIDs, serviceNames, nodeIDs, nodeNames map[string]bool }`; `func newServiceSet(services []serviceInfo, nodes []nodeInfo) serviceSet`, from both results of `listServices`; `func (l serviceSet) keepLabels(labels map[string]string) bool` applies the alert narrowing rule. Task 3 uses `serviceIDs`.
- `type alertsInput struct { ServiceID, ServiceName, NodeName, Severity string; Limit, Offset int }`, every field `omitempty`.
- `type alertRow struct { Name, Severity string; Labels map[string]string; Summary, Description string; StartsAt time.Time; Silenced bool; SilencedUntil *time.Time; PMMURL string }`, snake_case JSON. `Labels` is `json:"labels,omitempty"` and leaves out labels that start with `__`. `PMMURL` is `<base>graph/alerting/grafana/<rule uid>/view`, the pattern PMM's UI uses (`AlertStatusTable.utils.ts:85`), or `<base>graph/alerting/list` when there is no rule UID.
- `type alertsResult struct { Alerts []alertRow; Page page }` with `render()`: one line per alert (severity, name, service, node, start time, silence end, link) with its summary below, then the paging marker.
- Filters are exact. `service_id`, `service_name` and `node_name` compare labels; `severity` compares the `severity` label, case-insensitively. An alert without the label never matches a filter on it.
- Order: severity `critical`, `error`, `warning`, then other values alphabetically; then `starts_at`, newest first; then name.

**Steps:**
- Write `TestKeepLabels`, a table:
  - a service in `L`: kept;
  - a node in `L`: kept;
  - a service outside `L`: dropped;
  - a service in `L` with a node outside `L`: dropped;
  - no service or node label: shown;
  - an annotation that names a hidden service: no effect;
  - each of the four labels checked against its own set: a `node_name` equal to a listed service's name is still dropped.
- Write `TestAlertsTool` against a fixture with alerts for allowed service A, hidden service B, A's node, a node of B only, a server-level alert and a silenced alert:
  - the result holds A's alert, the node alert of A's node, the server-level alert and the silenced alert with `silenced_until`;
  - the `service_name`, `node_name` and `severity` filters;
  - a `service_id` filter for B is `not_found` with the fixed text, and the message contains neither B's ID nor any other service's name or ID;
  - the order above; 120 alerts with `limit` 50 set `page.truncated`;
  - a 401 from Grafana is `unauthorized`; a failing service list fails the call;
  - an alert for a service with no series in the last hour is dropped (Review Focus);
  - two services on one node, `L` holding one of them: the other service's alerts are dropped, and the node's own alerts are kept;
  - a negative Access Role filter: with `L` as VictoriaMetrics returns it for `{service_name!="B"}` (every node_exporter series, every service but B), B's alerts are dropped and the node-only alert of B's host is kept;
  - Access Control off: with `L` holding a ProxySQL service and a node-only host, the ProxySQL alert and the node-only alert are kept.
- Run, see FAIL. Implement: `listServices` (plan 06), then `Alerts`, narrowing, filters, order, `paginate`, render.
- Register the tool; add it to the name list, `TestErrorsCarryNoStructuredContent`, `TestEmptyAndDegradedResults` and the redaction exemptions; regenerate the golden file and the mock; list the Untrusted fields. Run `go test ./managed/services/mcp/...`, see PASS.
- Commit `PMM-15790 Add pmm_alerts`.

### Task 3: `pmm_advisors`

**Files:**
- Create: `managed/services/mcp/tools_advisors.go`, `tools_advisors_test.go`, `testdata/failed_checks*.json`
- Modify: `client.go` (the advisors client in `newClient`), `deps.go`, `mock_pmm_api_test.go`, `mcp.go`, `mcp_test.go`, `contract_test.go`, `testdata/tools_list.golden.json`

**Interfaces:**
- `pmmAPI` gains `FailedChecks(ctx context.Context, auth callerAuth) (*advisor_service.GetFailedChecksOKBody, error)`: `GET /v1/advisors/checks/failed` with no `service_id` and no paging parameters.
  - One such call returns every result, each with its `service_id` and `service_name` (`managed/services/management/checks.go:117`, `managed/services/checks/registry.go:103`). That is enough: `GET /v1/advisors/failedServices` isn't called, and per-severity counts are computed from the kept results.
  - The API returns results in map order, so MCP sorts them before paging.
- `type advisorsInput struct { ServiceID, ServiceName, Severity string; Limit, Offset int }`, every field `omitempty`.
- `type advisorRow struct { ServiceID, ServiceName, CheckName, Severity, Summary, Description, ReadMoreURL, PMMURL string }`, snake_case JSON. `Severity` is the enum name in lower case without `SEVERITY_` (`emergency` to `debug`), and the `severity` filter matches it exactly. `PMMURL` is `<base>graph/advisors/insights`.
- `type advisorsResult struct { Results []advisorRow; BySeverity map[string]int; Page page }` with `render()`. `BySeverity` is always non-nil (`{}` when nothing is left). It counts, per severity, the results that survive narrowing and the request's filters, across all pages, not only the returned page.
- Order: severity rank (`emergency` first), then service name, then check name.
- **Advisors disabled:** the API answers FailedPrecondition (`managed/services/management/checks.go:121`), which grpc-gateway sends as HTTP 400. The request carries no parameters, and that is the handler's only 400, so a 400 from it means Advisors are disabled. The tool answers `invalid_input` (the code HTTP 400 maps to, `errors.go:87`) with the message "Advisors are disabled in PMM's settings".

**Steps:**
- Write `TestAdvisorsTool` with an Editor fixture holding results for A (allowed) and B (hidden):
  - only A's results, and `by_severity` counts only them;
  - a `service_id` filter for B is `not_found` with the fixed text, without B's ID;
  - the `severity` filter, the order and paging;
  - a 403 (Viewer) is `unauthorized`;
  - a 400 gives `invalid_input` with "Advisors are disabled in PMM's settings";
  - no result left after narrowing: an empty list with `by_severity` `{}`, not a protocol error.
- Run, see FAIL; implement; register; add it to the name list, `TestErrorsCarryNoStructuredContent`, `TestEmptyAndDegradedResults` and the redaction exemptions; regenerate the golden file and the mock; list the Untrusted fields; run the package, see PASS.
- Commit `PMM-15790 Add pmm_advisors`.

### Task 4: `Instructions` and docs

**Files:**
- Modify: `managed/services/mcp/mcp.go` (`Instructions`), `documentation/docs/api/mcp.md`
- Test: `mcp_test.go` (`TestInitializeAndListTools`)

**Interfaces:** none.

**Steps:**
- `TestInitializeAndListTools`: the instructions contain `pmm_alerts` and `pmm_advisors`. Run, see FAIL.
- Add one line to `Instructions`: "For what is wrong now, call pmm_alerts (firing alerts) and pmm_advisors (failed Advisor checks; needs an Editor token)." Plan 03's line on untrusted fields covers their texts. Run, see PASS.
- `mcp.md`:
  - both tools, their filters and caps;
  - `pmm_advisors` needs an Editor token and returns `unauthorized` to a Viewer; use a separate Editor token only where Advisor results are needed (ADR-18);
  - both lists are narrowed to the caller's services to match its other results; Grafana's alert list and the Advisors page show the same user everything;
  - a service with no `up` sample for an hour leaves the list, and its alerts leave `pmm_alerts`.
- Commit `PMM-15790 Document pmm_alerts and pmm_advisors`.

### Task 5: api-tests and the PR

**Files:**
- Create: `api-tests/mcp/alerts_advisors_test.go`, using plan 06 Task 4's helpers

**Interfaces:** none.

**Steps:**
- On the live-check environment (00), with Task 1's alert set, Advisors enabled, and at least one Advisor check failing on two services A and B:
  - a Viewer whose Access Role allows A gets A's alert, the node alert of A's node and the server-level alert from `pmm_alerts`, and nothing of B;
  - an Editor with the same Access Role gets only A's results from `pmm_advisors`;
  - a Viewer gets `unauthorized` from `pmm_advisors`;
  - an alert of the folder without Viewer access doesn't reach a Viewer;
  - a Viewer whose Access Role is `{service_name!="B"}` doesn't get B's alerts, and gets the node-only alerts of every host;
  - with Advisors disabled, `pmm_advisors` answers `invalid_input` with "Advisors are disabled in PMM's settings".
- Record the results on PMM-15790.
- The last step of the plan (00): merge `origin/PMM-MCP-GA` into the branch, with `PMM-MCP-GA` behind 0; run a Feature Build from the branch, verify live, and open the PR `PMM-15790 Add pmm_alerts and pmm_advisors` into `PMM-MCP-GA`.
