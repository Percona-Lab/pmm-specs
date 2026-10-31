# Resolve first Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pmm_get_explain` and `pmm_get_schema` work from a `query_ref` or a `queryid` alone, resolved to one service the caller can see, and `pmm_get_schema` finds a MySQL query's tables by walking its EXPLAIN plan.

**Architecture:** A resolver turns a `queryRef` into a service, database, tables and stored example: candidates come from a QAN report grouped by `service_name` for that `queryid` and window, narrowed to the caller's inventory; the detail comes from the existing `fetchQueryDetail` for the chosen service. A plan walker reads table entries from `mysql_explain_json` output and maps aliases back to tables using the explained statement.

**Tech Stack:** Go 1.27, go-sdk v1.8.0, QAN API (`qan/metrics:getReport`, `qan:getMetrics`, `qan/query:getExample`), pmm-agent actions.

**Spec:** [spec §6](../spec.md#6-phase-2-the-rest-of-query-intelligence), [ADR-02](../adr/ADR-02-base-and-port.md), [ADR-05](../adr/ADR-05-read-only-tools.md), [ADR-11](../adr/ADR-11-output-contract.md).

## Global Constraints

- Needs plan 02 (`startLive`) and plan 03 (`addTool`, `queryRef`, `window`, result types).
- A caller's `service_id` is never used unchecked to fetch a plan: it must be one of the candidates.
- Without a window: the last hour, as `pmm_top_queries`; the result states the window used.
- Candidates: one → use it; several and no `service_id` → `invalid_input` listing only services the caller can see; none → `not_found` naming the window.
- An example whose `service_id` differs from the resolved service is never used.
- MySQL table discovery is best effort: base tables in the plan are returned; derived tables, CTEs and anything needing SQL parsing are listed in `unresolved`, never guessed.
- A live plan is labelled as the plan the database would choose now.
- One `pmm_get_schema` call holds one live slot (plan 02), whether it runs EXPLAIN, the DDL actions, or both.

## Review Focus

- **A query seen yesterday and passed by `queryid` alone today** returns `not_found` that names the searched window and says to pass `query_ref`: Task 3 tests the message.
- **Services with the same fingerprint where the caller sees only one** resolve to that one, without naming the hidden one anywhere: Task 3 tests the candidate list and the error text.
- **A MySQL plan with a table name that is both an alias and a real table elsewhere in the statement** must map by alias first: Task 2 fixture `mysql-alias-shadows-table`.
- **A PostgreSQL relation name with a schema prefix (`public.country`)** must reach `postgres_show_create_table` in the form pmm-agent accepts: Task 5 step 1 checks it on a live server before coding.
- **The resolver's extra QAN call must not run on the old addressing** (`service_id` + `database` + `tables`): Task 5 asserts the fake PMM saw no `getReport` call in that mode.

---

### Task 1: MySQL EXPLAIN fixtures

**Files:** Create `managed/services/mcp/testdata/explain/` with `<version>-<case>.json` (pmm-agent's `mysql_explain_json` action output, as `GET /v1/actions/{id}` returns it) and `<version>-<case>.sql` (the statement).

- [ ] **Step 1: Capture on a CHAOS VM** (Feature Build of `PMM-MCP-GA`, `chaos-docker-provisioning`), for each MySQL and Percona Server major version pmm-qa provisions for PMM 3 (at least 8.0 and 8.4), through `POST /v1/actions:startServiceAction` with `mysql_explain_json`, the cases: `single`, `join-aliases` (`FROM orders o JOIN customers c`), `join-no-aliases`, `schema-qualified`, `subquery-where`, `derived-table`, `cte`, `union`, `alias-shadows-table` (`FROM a b JOIN b a`). On 8.4, also `join-aliases` with `SET GLOBAL explain_json_format_version=2`, saved as `8.4-v2-join-aliases`.
- [ ] **Step 2: Record what `table_name` holds in format version 1** (alias or table) on PMM-15529 and in spec §6.2 through a pmm-specs PR, replacing the [I] there.
- [ ] **Step 3: Commit** `PMM-15529 Add MySQL EXPLAIN JSON fixtures`.

### Task 2: Plan walker

**Files:** Create `managed/services/mcp/plan_tables.go`, `plan_tables_test.go`.

**Interfaces:**
- Produces:
  - `type planTable struct { Schema, Name, Alias string }`; `Name` keeps MySQL's `<derived2>`, `<union1,2>`, `<subquery2>` forms.
  - `func planTables(plan []byte) ([]planTable, error)`: walks the whole JSON tree; collects each `table` object's `table_name` (format 1) and each object with `table_name` plus `alias`/`schema_name` (format 2); unique, in plan order.
  - `func resolveTables(tables []planTable, statement, database string) (resolved []tableRef, unresolved []string)`: a format 2 entry gives the name directly; a format 1 `table_name` is looked up first as an alias, then as a table, in an alias map built from the statement's `FROM` and `JOIN` clauses (identifier, optionally schema-qualified and backquoted, then an optional alias with or without `AS`); `<…>` names and names not found go to `unresolved`. A schema-qualified identifier sets `tableRef.database`; otherwise `database`.

- [ ] **Step 1: Write `TestPlanTablesFixtures`:** one row per Task 1 fixture with the expected `resolved` and `unresolved`; e.g. `8.0-join-aliases` → resolved `orders`, `customers`; `8.0-derived-table` → its base table resolved and `<derived2>` unresolved; `alias-shadows-table` → `a` and `b` each once. Add `TestPlanTablesRejectsNonJSON`: `planTables([]byte("x"))` returns an error.
- [ ] **Step 2: Run, see FAIL; implement; run, see PASS.** `go test ./managed/services/mcp/ -run 'TestPlanTables' -v`
- [ ] **Step 3: Commit** `PMM-15529 Find MySQL tables in the EXPLAIN plan`.

### Task 3: Resolver

**Files:** Create `managed/services/mcp/resolve.go`, `resolve_test.go`; Modify `client.go` only if a request field is missing; Fixtures `testdata/report_by_service_*.json`.

**Interfaces:**
- Consumes: `queryRef`, `window` (plan 03), `listServices`, `fetchQueryDetail`, `parseWindow`.
- Produces:
  - `type resolvedQuery struct { Service serviceInfo; Ref queryRef; Database string; Tables []string; Example string }`; `Ref.ServiceID` is always set.
  - `func (s *Service) resolveQuery(ctx context.Context, auth callerAuth, ref queryRef) (*resolvedQuery, error)`
  - `func refFromInput(ref *queryRef, queryID, serviceID, periodFrom, periodTo string, now time.Time) (queryRef, error)`: builds the reference from either form; both forms at once, or neither, is `invalid_input`.

- [ ] **Step 1: Write `TestResolveQuery`**, table-driven against the fake PMM (routes for `POST /v1/qan/metrics:getReport` grouped by `service_name`, `GET /v1/inventory/services`, `POST /v1/qan:getMetrics`, `POST /v1/qan/query:getExample`):
  - one candidate → that service; the `getReport` body has `group_by: service_name`, label `queryid`, and the request's window;
  - two candidates, no `service_id` → `invalid_input`, message lists both as `name (id)`;
  - two in QAN, one in the caller's inventory → the visible one, and the message of any error never contains the hidden name;
  - `service_id` not a candidate → `not_found`;
  - no candidates → `not_found` containing both window ends and `query_ref`;
  - example with another `service_id` → `Example` empty;
  - window from a `query_ref` a day old is the window sent to QAN.
- [ ] **Step 2: Write `TestRefFromInput`:** `query_ref` alone; `queryid` with and without a window (default last hour); both forms → `invalid_input`; neither → `invalid_input`.
- [ ] **Step 3: Run, see FAIL; implement; run, see PASS.** `go test ./managed/services/mcp/ -run 'TestResolveQuery|TestRefFromInput' -v`
- [ ] **Step 4: Commit** `PMM-15529 Resolve a query to one visible service`.

### Task 4: `pmm_get_explain` from a query reference

**Files:** Modify `managed/services/mcp/tools_actions.go`; Test `tools_actions_test.go`.

**Interfaces:**
- Produces: `explainInput` gains `QueryRef *queryRef \`json:"query_ref,omitempty"\``, `PeriodFrom string \`json:"period_from,omitempty"\``, `PeriodTo string \`json:"period_to,omitempty"\``; `ServiceID` becomes optional. `explainResult.QueryRef` is the resolved reference; for MySQL and MongoDB the text carries "Live plan: what the database would choose now, not during the window."

- [ ] **Step 1: Extend `TestExplainTool`:** MySQL by `queryid` alone uses the resolved service and database in the action body; MongoDB uses the resolver's example; PostgreSQL calls `GetQueryPlan` with the resolved `service_id`; `query` (MongoDB explicit statement) with `service_id` still works without the resolver.
- [ ] **Step 2: Run, see FAIL; route the `queryid`/`query_ref` forms through `refFromInput` and `resolveQuery`; run the package, see PASS.**
- [ ] **Step 3: Commit** `PMM-15529 Explain a query from its reference`.

### Task 5: `pmm_get_schema` from a query reference

**Files:** Modify `managed/services/mcp/tools_actions.go`; Test `tools_actions_test.go`, `api-tests/mcp/mcp_test.go`.

**Interfaces:**
- Consumes: `resolveQuery`, `planTables`, `resolveTables`, `tableInfo`, `startLive`.
- Produces: `schemaInput` gains `QueryID`, `QueryRef`, `PeriodFrom`, `PeriodTo`; `Database` and `Tables` are required only in the old form. `schemaResult` gains `Unresolved []string \`json:"unresolved,omitempty"\`` (Untrusted).

- [ ] **Step 1: Check on a live server** that `postgres_show_create_table` accepts the `public.country` form pg_stat_monitor sends in `tables`; if not, split it into schema and name in this task. Record the answer on PMM-15529.
- [ ] **Step 2: Extend `TestSchemaTool`:**
  - PostgreSQL by `queryid`: tables from the example;
  - MySQL by `queryid`: one `mysql_explain_json` action, then the DDL actions for the resolved tables, `unresolved` from the plan;
  - MongoDB by `queryid`: `invalid_input`, schema is MySQL and PostgreSQL only;
  - old form: no `getReport` call recorded;
  - with the caller at 2 live calls: `rate_limited` before any action starts.
- [ ] **Step 3: Run, see FAIL; implement; run the package, see PASS.**
- [ ] **Step 4: Add api-test `TestSchemaFromQueryID`:** take the busiest `pmm_top_queries` row whose fingerprint contains ` JOIN `, call `pmm_get_schema` with its `query_ref`, assert one table block per joined base table; skip with a message when no such row exists.
- [ ] **Step 5: Verify live** on a Feature Build with a MySQL join workload; then update `documentation/docs/api/mcp.md` (`query_ref`, `pmm_get_schema` by `queryid`, best-effort MySQL tables).
- [ ] **Step 6: Commit** `PMM-15529 Fetch a query's table definitions from its reference`.
