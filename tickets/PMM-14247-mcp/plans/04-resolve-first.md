# Resolve first Implementation Plan

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans).

**Goal:** `pmm_get_explain` and `pmm_get_schema` work from a `query_ref` or a `queryid` alone, resolved to one service in the caller's service list; `pmm_get_schema` finds a MySQL query's tables by walking its EXPLAIN plan; `pmm_query_detail` is narrowed to the same list.

**Architecture:** A resolver turns a `queryRef` into a service, database, tables and stored example: candidates come from a QAN report grouped by `service_name` for that `queryid` and window, restricted to the caller's service list; the detail comes from the existing `fetchQueryDetail` for the chosen service. A plan walker reads table entries from `mysql_explain_json` output and maps format 1 names back to tables with a best-effort alias map.

**Tech Stack:** Go 1.27, go-sdk v1.8.0, QAN API (`qan/metrics:getReport`, `qan:getMetrics`, `qan/query:getExample`), pmm-agent actions; Docker for the fixture capture (Task 1 only).

**Spec:** [spec §6](../spec.md#6-phase-2-the-rest-of-query-intelligence), [ADR-02](../adr/ADR-02-base-and-port.md), [ADR-03](../adr/ADR-03-api-only-data-path.md), [ADR-05](../adr/ADR-05-read-only-tools.md), [ADR-08](../adr/ADR-08-inventory-under-access-roles.md), [ADR-11](../adr/ADR-11-output-contract.md).

## Global Constraints

- Needs plan 02 (`startLive`) and plan 03 (`addTool`, `queryRef`, `window`, `partError`, result types), and the design review (00).
- One branch, `PMM-15529-resolve-first`, and one PR into `PMM-MCP-GA` after Task 6 ([00](00-roadmap.md#branch-and-pr-rules)). Task 1 Step 3 is a pmm-specs PR of its own.
- Every service lookup goes through the caller's service list (`listServices`, `engineOf`). Plan 06 later changes where that list comes from, to metric series (ADR-08); this plan calls only those two functions.
- Tasks 4 and 5 change tool inputs and outputs: regenerate `testdata/tools_list.golden.json` (`-update`) and add `unresolved` and `not_fetched` to `TestUntrustedFieldsMarked` (plan 03, Task 8).
- Every input field of `pmm_get_explain` and `pmm_get_schema` carries `omitempty`: jsonschema-go v0.4.3 makes every other field required (`jsonschema/infer.go:342-343`), and the SDK refuses such a call before the handler runs, outside the error envelope (plan 03). The handler checks every form and combination itself and answers `invalid_input` with the envelope; no case here relies on an SDK refusal for its code.
- A caller's `service_id` is never used unchecked to fetch a plan: it must be in the caller's service list and one of the candidates.
- A `not_found` message never echoes an ID or name the caller sent. For a service outside the list the text is "not in your service list (services that sent metrics in the last hour)", plus the tool's hint.
- Without a window: the last hour, as `pmm_top_queries`. The result's `query_ref` carries the window used.
- Candidates: one → use it; several and no `service_id` → `invalid_input` listing only services in the caller's list; none → `not_found` naming the window.
- An example whose `service_id` differs from the resolved service is never used.
- **MySQL EXPLAIN picks its own statement.** pmm-managed reads it from QAN by `service_id` and `queryid`, with no window (`managed/services/agents/actions.go:78`, `qan-api2/models/metrics.go:1117-1118`): the stored example when there is one, otherwise the fingerprint, which then needs `placeholders` (`actions.go:84`). The window chooses the candidate service only. MongoDB explains the resolver's example from the window.
- **No stored example:**

  | Tool and engine | Answer |
  |---|---|
  | `pmm_get_explain`, MySQL | `invalid_input`: pass `placeholders` (one value per `?`, in order) and `database`, or enable query examples |
  | `pmm_get_explain`, MongoDB | `no_query_source`, as today (`tools_actions.go:244`) |
  | `pmm_get_explain`, PostgreSQL | unaffected: the stored plan comes from pg_stat_monitor; none is `not_found`, as today |
  | `pmm_get_schema` by `queryid`, MySQL | the EXPLAIN's error, with the hint: pass `placeholders`, or `database` and `tables` |
  | `pmm_get_schema` by `queryid`, PostgreSQL | `no_query_source` when QAN has no `tables` for the query: pass `database` and `tables` |

- `pmm_get_schema` supports MySQL and PostgreSQL. A MongoDB service answers `invalid_input` in every input form, before any action.
- MySQL table discovery is best effort. Base tables in the plan are returned. Format 1 names are mapped through a best-effort alias map (Task 2); derived tables, CTEs, materialized subqueries and names the map doesn't resolve are listed in `unresolved`, never guessed.
- The explained statement in the action output is used only to build the alias map: never rendered, never logged. With a stored example it is the example itself, literals included (`qan-api2/models/metrics.go:1165-1167`).
- A live plan is labelled as the plan the database would choose now.
- One `pmm_get_schema` call holds one live slot (plan 02), whether it runs EXPLAIN, the DDL actions, or both.

## Review Focus

- **A query seen yesterday and passed by `queryid` alone today** returns `not_found` that names the searched window and says to pass `query_ref`: Task 3 tests the message.
- **Services with the same fingerprint where the caller's list has only one** resolve to that one, without naming the other anywhere: Task 3 tests the QAN request, the candidate list and the error text.
- **A MySQL plan with a table name that is both an alias and a real table elsewhere in the statement** must map by alias first: Task 2 fixtures `*-alias-shadows-table`.
- **A CTE named like a real table** is listed in `unresolved`, not fetched as that table: Task 2 fixtures `*-cte-shadows-table`.
- **A `service_id` outside the caller's list** never comes back in a message, in any tool of this plan: Tasks 3 and 6 assert the fixed text.
- **A `queryid`-only call** reaches the resolver instead of failing input validation: Tasks 4 and 5 call each tool with `queryid` alone.
- **A PostgreSQL relation outside the monitoring user's `search_path`** answers `not_found` for that table only: Task 5 records the limit and checks it live.
- **The resolver's extra QAN call must not run on the old addressing** (`service_id` + `database` + `tables`): Task 5 asserts the fake PMM saw no `getReport` call in that mode.

---

### Task 1: MySQL EXPLAIN fixtures

**Files:** Create in `managed/services/mcp/testdata/explain/`: `schema.sql` (the tables every case uses), `<case>.sql` (one statement per case), `capture.sh`, and the plans `<flavor>-<version>-<case>.json` (`flavor`: `mysql` or `ps`).

- [ ] **Step 1: Write `capture.sh <image> <flavor> <version>`.** It starts a throwaway container of the image, loads `schema.sql`, and for each `<case>.sql` runs `EXPLAIN FORMAT=JSON <statement>` and `SHOW WARNINGS` in one session. It writes the plan with a `warnings` array added in pmm-agent's shape (`Level`, `Code`, `Message`; `agent/runner/actions/mysql_explain_action.go:252-268`), as `<flavor>-<version>-<case>.json`. On 8.4 it runs every case again after `SET explain_json_format_version=2`, saved as `<flavor>-8.4-v2-<case>.json`. Run it where Docker is available; the fixtures are committed, so unit tests need only Go.
- [ ] **Step 2: Capture** for MySQL and Percona Server 5.7, 8.0 and 8.4 (`mysql:5.7`, `mysql:8.0`, `mysql:8.4`, `percona/percona-server:5.7`, `percona/percona-server:8.0`, `percona/percona-server:8.4`). 5.7 is in scope: PMM documents MySQL 5.6 and later and Percona Server 5.7 (`documentation/docs/install-pmm/install-pmm-client/connect-database/mysql/mysql.md:138-144`). MySQL 5.6 and MariaDB are not captured; their plans go through the same walker, and what it can't map is `unresolved`. The cases: `single`, `join-aliases` (`FROM orders o JOIN customers c`), `join-no-aliases`, `schema-qualified`, `subquery-where`, `derived-table`, `cte`, `cte-shadows-table` (`WITH orders AS (…) SELECT … FROM orders`), `union`, `alias-shadows-table` (`FROM a b JOIN b a`).
- [ ] **Step 3: Record the findings** in spec §6.2 (replacing the [I] there) and in this plan's Task 2 through one pmm-specs PR, before Task 2 starts:
  - what format 1's `table_name` holds: the alias or the table;
  - how a derived table, a CTE and a union branch appear in each format: `<derivedN>`, `<unionN,M>`, `materialized_from_subquery`, the CTE's name, and the format 2 equivalents;
  - whether Note 1003 in `warnings` names every base table as `` `schema`.`table` `alias` `` on every captured version [I: MySQL prints the rewritten query there].
- [ ] **Step 4: Commit** `PMM-15529 Add MySQL EXPLAIN JSON fixtures`.

### Task 2: Plan walker

**Files:** Create `managed/services/mcp/plan_tables.go`, `plan_tables_test.go`.

**Interfaces:**
- Produces:
  - `func decodeExplainEnvelope(output string) ([]byte, string, error)`: unwraps `{explain_result: <base64 plan>, explained_query, is_dml}` into the plan and the explained statement, for resolution only; `decodeExplainOutput` keeps rendering.
  - `type planTable struct { Schema, Name, Alias string; Derived bool }`; `Name` keeps MySQL's `<derived2>`, `<union1,2>`, `<subquery2>` forms.
  - `func planTables(plan []byte) ([]planTable, error)`: walks the whole JSON tree; skips the `warnings` and `real_table_name` keys pmm-agent adds (`mysql_explain_action.go:268-269`); collects each `table` object's `table_name` (format 1) and each object with `table_name` plus `alias`/`schema_name` (format 2), unique, in plan order; an entry with `materialized_from_subquery` (or the format 2 equivalent Task 1 recorded) is `Derived`, and the query block inside it is still walked.
  - `func aliasMap(plan []byte, statement string) map[string]tableRef`: alias or table name → table. Its source is the one Task 1 chose: Note 1003 when it names every base table on every captured version, else the statement's `FROM` and `JOIN` clauses (identifier, optionally schema-qualified and backquoted, then an optional alias with or without `AS`). Names declared in `WITH` are never entries.
  - `func resolveTables(tables []planTable, aliases map[string]tableRef, database string) ([]tableRef, []string)`: the resolved tables and the unresolved names. A format 2 entry gives the name directly; a format 1 name is looked up as an alias first, then as a table name. `<…>` names, `Derived` entries, CTE names and names not in the map go to `unresolved`. A schema-qualified name sets `tableRef.database`; otherwise `database`.

- [ ] **Step 1: Write `TestPlanTablesFixtures`:** one row per Task 1 fixture, with the expected `resolved` and `unresolved` written from Task 1's recorded findings. At least: `join-aliases` → `orders`, `customers`; `derived-table` → its base table resolved and the derived entry unresolved; `cte` and `cte-shadows-table` → the CTE's name unresolved and the base table inside it resolved; `alias-shadows-table` → `a` and `b` each once. Add:
  - `TestPlanTablesRejectsNonJSON`: `planTables([]byte("x"))` returns an error;
  - `TestPlanTablesSkipsAgentKeys`: a plan with `real_table_name` and `warnings` gives the same tables as without them;
  - `TestAliasMap`: the backquoted fingerprint form (`` FROM `shop`.`orders` `o` ``) maps like the plain form; an empty statement and no Note 1003 give an empty map, so every format 1 name is unresolved;
  - `TestDecodeExplainEnvelope`: returns the decoded plan and `explained_query` whatever `PMM_MCP_RAW_SQL` is.
- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.** `go test ./managed/services/mcp/ -run 'TestPlanTables|TestAliasMap|TestDecodeExplainEnvelope' -v`
- [ ] **Step 3: Commit** `PMM-15529 Find MySQL tables in the EXPLAIN plan`.

### Task 3: Resolver

**Files:** Create `managed/services/mcp/resolve.go`, `resolve_test.go`; Modify `client.go` only if a request field is missing; Fixtures `testdata/report_by_service_*.json`.

**Interfaces:**
- Consumes: `queryRef`, `window` (plan 03), `listServices`, `fetchQueryDetail`, `parseWindow`.
- Produces:
  - `type queryRefInput struct { QueryID string \`json:"queryid,omitempty"\`; ServiceID string \`json:"service_id,omitempty"\`; PeriodFrom string \`json:"period_from,omitempty"\`; PeriodTo string \`json:"period_to,omitempty"\` }`: the input form of `queryRef`, with string times, so a bad time is `invalid_input` from `refFromInput`, not an SDK decoding error.
  - `type resolvedQuery struct { Service serviceInfo; Ref queryRef; Database string; Tables []string; Example string }`; `Ref.ServiceID` is always set.
  - `func (s *Service) resolveQuery(ctx context.Context, auth callerAuth, ref queryRef) (*resolvedQuery, error)`
  - `func refFromInput(ref *queryRefInput, queryID, serviceID, periodFrom, periodTo string, now time.Time) (queryRef, error)`: builds the reference from either form. `invalid_input`: neither form; a `query_ref` beside any of `queryid`, `service_id`, `period_from` or `period_to` (a `query_ref` carries its own service and window); a `query_ref` without `queryid`, `period_from` or `period_to`; `service_id` or a period without `queryid`; a time `parseWindow` rejects.
- Rules:
  - A given `service_id` not in the caller's service list is `not_found` with the text "not in your service list (services that sent metrics in the last hour)", before any QAN call. An empty list is `not_found` the same way.
  - A `service_id` in the list on which the query wasn't seen is `not_found`: "the query was not seen on that service in <window>", without the ID.
  - Candidates come from one `getReport`: `group_by: service_name`, label `queryid`, label `service_id` with the given ID or else every ID of the caller's list (each passes `checkQANValue`, as `service_id` does today), `limit: 100`, the reference's window. Rows after the total row (empty dimension) map to services by name; a row whose name is not in the list is dropped.
  - Several candidates: the `invalid_input` message lists up to 20 as `name (id)`, then `and N more` from `total_rows`, and says to pass `service_id`.
  - `Database`: for MySQL, `metadata.schema` from `getMetrics`, else the example's `schema`; for PostgreSQL and MongoDB, `metadata.database` (`tools_qan.go:445`).
  - `Tables`: the example's `tables` (PostgreSQL); empty for MySQL and MongoDB.

- [ ] **Step 1: Write `TestResolveQuery`**, table-driven against the fake PMM (routes for `POST /v1/qan/metrics:getReport` grouped by `service_name`, the caller's service list, `POST /v1/qan:getMetrics`, `POST /v1/qan/query:getExample`):
  - one candidate → that service; the `getReport` body has `group_by: service_name`, labels `queryid` and `service_id` (the list's IDs), `limit: 100`, and the request's window;
  - two candidates, no `service_id` → `invalid_input`, message lists both as `name (id)`;
  - 130 candidates in `total_rows` → the message lists 20 and says `and 110 more`;
  - the report fixture also has a row for a service outside the caller's list → that row is dropped, and no request label or message names it;
  - `service_id` outside the list → `not_found` whose text is exactly the fixed one, without the ID, and no `getReport` call;
  - `service_id` in the list but not a candidate → `not_found` naming the window, without the ID;
  - no candidates → `not_found` containing both window ends and `query_ref`, without the `queryid`;
  - example with another `service_id` → `Example` empty;
  - `Database` per engine, from the fields above;
  - window from a `query_ref` a day old is the window sent to QAN.
- [ ] **Step 2: Write `TestRefFromInput`:** `query_ref` alone; `queryid` with and without a window (default last hour); both forms → `invalid_input`; neither → `invalid_input`; `query_ref` with a flat `service_id` or `period_from` and no `queryid` → `invalid_input`; `service_id` alone → `invalid_input`; a `query_ref` with `period_from: "yesterday"` → `invalid_input`. Every case answers through the handler: text `error: invalid_input`, and `_meta` set.
- [ ] **Step 3: Run, see FAIL; implement; run, see PASS.** `go test ./managed/services/mcp/ -run 'TestResolveQuery|TestRefFromInput' -v`
- [ ] **Step 4: Commit** `PMM-15529 Resolve a query to one service in the caller's list`.

### Task 4: `pmm_get_explain` from a query reference

**Files:** Modify `managed/services/mcp/tools_actions.go`; Test `tools_actions_test.go`.

**Interfaces:**
- Produces: `explainInput.ServiceID` gets the tag `json:"service_id,omitempty"`; `explainInput` gains `QueryRef *queryRefInput \`json:"query_ref,omitempty"\``, `PeriodFrom string \`json:"period_from,omitempty"\``, `PeriodTo string \`json:"period_to,omitempty"\``, and loses `Query`: MongoDB explains only the example QAN stored (ADR-05), and `storedExample` is removed. `database` and `placeholders` stay MySQL inputs; a given `database` overrides the resolved one. `explainResult.QueryRef` is the resolved reference; for MySQL and MongoDB the text carries "Live plan: what the database would choose now, not during the window."
- The 1064 hint (`tools_actions.go:172-178`) also covers pmm-managed's `placeholders count is not correct` (HTTP 400, `invalid_input`).

- [ ] **Step 1: Extend `TestExplainTool`:**
  - `queryid` alone, with no `service_id`, reaches the resolver: the fake PMM recorded a `getReport` call;
  - MySQL by `queryid` uses the resolved service and database in the action body;
  - MySQL without a stored example: a 400 `placeholders count is not correct` from the action start, and a 1064 from the action, both answer `invalid_input` naming `placeholders`;
  - MongoDB uses the resolver's example; with no example in the window → `no_query_source`;
  - PostgreSQL calls `GetQueryPlan` with the resolved `service_id`;
  - the golden file shows no `query` property. A call that still sends it is refused by the SDK, outside the envelope (plan 03 pins that shape); this plan asserts no code for it;
  - `query_ref` together with `queryid` → `invalid_input`.
- [ ] **Step 2: Run, see FAIL; route the `queryid`/`query_ref` forms through `refFromInput` and `resolveQuery`; update the tool description (no `query`; `query_ref` or `queryid`); run the package, see PASS.**
- [ ] **Step 3: Commit** `PMM-15529 Explain a query from its reference`.

### Task 5: `pmm_get_schema` from a query reference

**Files:** Modify `managed/services/mcp/tools_actions.go`, `mcp.go` (`Instructions`); Test `tools_actions_test.go`, `mcp_test.go`, `api-tests/mcp/mcp_test.go`.

**Interfaces:**
- Consumes: `resolveQuery`, `decodeExplainEnvelope`, `planTables`, `aliasMap`, `resolveTables`, `tableInfo`, `startLive`.
- Produces:
  - `schemaInput.ServiceID`, `Database` and `Tables` gain `omitempty`; `schemaInput` gains `QueryID`, `QueryRef *queryRefInput`, `PeriodFrom`, `PeriodTo` and `Placeholders []string` (MySQL, query forms only), all `omitempty`.
  - `schemaResult` gains `Unresolved []string \`json:"unresolved,omitempty"\`` (Untrusted), `NotFetched []string \`json:"not_fetched,omitempty"\`` (Untrusted) and `QueryRef *queryRef \`json:"query_ref,omitempty"\``, set in the query forms; its period is the window used (ADR-11 provenance).
- Input forms: the old one, `service_id` + `database` + `tables`; or a query form, `query_ref` or `queryid` with optional `service_id`, `period_from`, `period_to`. `database` or `tables` with a query form, `placeholders` with the old form, and an old form missing any of its three fields are `invalid_input`, checked in the handler. `info_types` works with both.
- MySQL in a query form: one `mysql_explain_json` action (resolved service and database, `placeholders`), then the DDL actions for the resolved tables. If the EXPLAIN fails, the call fails with its error; a missing example gets the hint from Global Constraints, and no DDL action runs. Resolved tables beyond the 10-table cap, in plan order, are not fetched: they are listed in `not_fetched`, and the text says the cap was reached.
- PostgreSQL relations: the `schema.table` form from pg_stat_monitor is passed as is. Decision, from the code: both PostgreSQL actions split it on `.` (`agent/runner/actions/postgresql_show_create_table_action.go:178`, `postgresql_show_index_action.go:93`). The DDL action also requires `pg_table_is_visible` (`postgresql_show_create_table_action.go:192`), so a table in a schema outside the monitoring user's `search_path` answers `not_found` for that table; `mcp.md` states this limit.

- [ ] **Step 1: Extend `TestSchemaTool`:**
  - `queryid` alone, with no `service_id`, `database` or `tables`, reaches the resolver;
  - PostgreSQL by `queryid`: tables from the example; no `tables` in QAN → `no_query_source`;
  - MySQL by `queryid`: one `mysql_explain_json` action, then the DDL actions for the resolved tables, `unresolved` from the plan, and `query_ref` with the window used;
  - MySQL by `queryid` whose EXPLAIN answers 1064: `invalid_input` naming `placeholders`, and no DDL action started;
  - with `PMM_MCP_RAW_SQL` off, an action output whose `explained_query` holds a literal: the literal is in neither rendering, and `TestRedactionInBothRenderings` (plan 03) gains this case;
  - MongoDB, by `queryid` and in the old form: `invalid_input`, no action started;
  - `queryid` with `tables`, and `service_id` with `database` but no `tables` → `invalid_input` with the envelope;
  - a join of 12 base tables: 10 table blocks and 2 names in `not_fetched`, none in `unresolved`;
  - old form: no `getReport` call recorded;
  - with the caller at 2 live calls: `rate_limited` before any action starts.
- [ ] **Step 2: Add the `query_ref` line to `Instructions`:** "Pass the `query_ref` from `pmm_top_queries` or `pmm_query_detail` to `pmm_get_explain` and `pmm_get_schema`; a `queryid` alone searches the last hour." Assert `query_ref` in `TestInitializeAndListTools` (plan 03 doesn't).
- [ ] **Step 3: Run, see FAIL; implement; run the package, see PASS.**
- [ ] **Step 4: Add api-test `TestSchemaFromQueryID`** with a known workload. Before it runs, load `managed/services/mcp/testdata/explain/schema.sql` into the live environment's MySQL 8.0 service, run `join-aliases.sql` from the same folder 100 times with the `mysql` client, and wait 2 minutes for QAN. The test calls `pmm_top_queries` for that service with `search: "customers"`, takes the row whose fingerprint joins `orders` and `customers`, calls `pmm_get_schema` with its `query_ref`, and asserts one table block each for `orders` and `customers` and no `unresolved`. It fails, not skips, when the row is missing.
- [ ] **Step 5: Verify live** on the Feature Build:
  - `pmm_get_explain` with the same `query_ref` returns a MySQL plan labelled as live;
  - at least one hour after the workload stops, `pmm_get_schema` with that `queryid` alone answers `not_found` naming the window, and with the saved `query_ref` returns the two tables;
  - on PostgreSQL 17 with pg_stat_monitor, a query on `public.<table>` returns its DDL, and a table in a schema outside the monitoring user's `search_path` answers `not_found` for that table only.
- [ ] **Step 6: Update `documentation/docs/api/mcp.md`:** `query_ref`, `pmm_get_schema` by `queryid`, best-effort MySQL tables, the `search_path` limit, the removed MongoDB `query` input. Commit `PMM-15529 Fetch a query's table definitions from its reference`.

### Task 6: `pmm_query_detail` narrowed to the caller's service list

**Files:** Modify `managed/services/mcp/tools_qan.go` (`queryDetail`, `fetchQueryDetail`); Test `tools_qan_test.go`.

**Interfaces:**
- A given `service_id` not in the caller's service list is `not_found` with the text "not in your service list (services that sent metrics in the last hour)", before any QAN call.
- Without one, `getMetrics` and `getExample` carry the label `service_id` with every ID of the caller's list (each passes `checkQANValue`), so QAN sums only those services and returns only their examples. An empty list is `not_found` the same way.
- The existing "no data" message (`tools_qan.go:345-346`) names the window and drops the `queryid`.

- [ ] **Step 1: Extend `TestQueryDetailTool`:** a `service_id` outside the list → `not_found` whose text is exactly the fixed one, without the ID, and no QAN call; without `service_id`, both request bodies carry the list's IDs; no error text names a service outside the list.
- [ ] **Step 2: Run, see FAIL; implement; run the package, see PASS.**
- [ ] **Step 3: Add the rule to `mcp.md`; commit** `PMM-15529 Narrow pmm_query_detail to the caller's services`.
- [ ] **Step 4: Open the PR** ([00](00-roadmap.md#branch-and-pr-rules)): merge `origin/PMM-MCP-GA` (behind 0) into the branch, run a Feature Build, run the api-tests and the triage on it, and open `PMM-15529 Resolve queries to one service in the caller's list` into `PMM-MCP-GA` with the Feature Build link.
