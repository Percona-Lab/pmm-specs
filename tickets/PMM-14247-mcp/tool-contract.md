# MCP tool contract (PMM-14247)

- **Date:** 2026-11-05, revised 2026-11-06 after the security design review, and 2026-11-09 for the look-back of the caller's service list (a user decision, plan 06).
- **Ticket:** [PMM-15530](https://perconadev.atlassian.net/browse/PMM-15530), phase 3 of PMM-14247.
- **Decision:** [ADR-11](adr/ADR-11-output-contract.md) and [spec §8](spec.md#8-phase-3-output-contract). [Plan 03](plans/03-output-contract.md) builds the contract; this document is its Task 1 and is reviewed before Tasks 2 to 9 change any code. The security design review reads it with the rest of this folder ([spec §3.1](spec.md#31-order-from-here)).
- **Code base:** percona/pmm `PMM-MCP-GA` at `911910199`, with plans 01 and 02 merged. Paths are under `managed/services/mcp/` unless they say otherwise, and line numbers refer to that commit. go-sdk v1.8.0 and jsonschema-go v0.4.3, from `go.mod`.

Today's code has the error codes and the `error: <code>` text; the rest of the contract is what plan 03 builds, and what plans 04 to 07 build on. **As built** (revised 2026-11-07): plans 01 to 05 are built, in percona/pmm `PMM-15790-metrics-tools` at `747e1f968`. The rows and notes of their tools, and [§8.1](#81-budgets-of-the-metric-tools), describe that code, which they cite by function name; the golden `tools/list` file, `managed/services/mcp/testdata/tools_list.golden.json`, is the authority for every input and output field. Plans 06 and 07 are still design.

Statements about today's code carry **[V]**, verified by reading it or the SDK's source. **[I]** marks what is inferred, here or in the ADR it comes from, and not yet settled.

---

## 1. Scope

This document holds:
- the rules every tool follows: results ([§2](#2-one-result-two-renderings)), errors ([§3](#3-errors)), paging ([§4](#4-paging)), provenance ([§5](#5-provenance)), partial results ([§6](#6-partial-results)) and untrusted fields ([§7](#7-untrusted-fields));
- one table with a row per tool ([§8](#8-tools));
- the decisions taken with it ([§9](#9-decisions-recorded-here)), and the question left for its review ([§10](#10-question-for-the-review)).

Inputs and output schemas are not written out here. Plan 03's `TestToolsListGolden` snapshots `tools/list` (names, descriptions, input and output schemas, annotations) in `testdata/tools_list.golden.json`, so a change to them shows up as a diff in review. Caps are in [spec §8](spec.md#8-phase-3-output-contract), the one place where they change; where a note here quotes one, spec §8 governs.

Until the release, the contract may change freely; afterwards, only additively (ADR-11). A change this document's review asks for is made in plan 03's types before coding, and in plans 04, 05 and 07 in the same pmm-specs PR, so those plans start from the reviewed contract.

## 2. One result, two renderings

- Each tool has a Go result type. The handler builds one value; the SDK validates it against the type's output schema and sends it as `structuredContent`. The text content, "View in PMM" links included, is rendered from the same value (`render()`).
- Tools register through plan 03's `addTool`: `Out = any`, and `Tool.OutputSchema = jsonschema.For[T](nil)` for the result type `T`. Never `ToolHandlerFor[In, T]` with a typed `T`: go-sdk v1.8.0 then sends `T`'s zero value as structured content next to `isError` (`mcp/server.go:420-468`) [V]. `addTool` panics at registration when the schema can't be built, as `mcp.AddTool` does, and keeps today's call deadline, `PMM_MCP_ACTION_TIMEOUT` plus 45 s (`tools.go:27`, `:40`), and logging.
- ADR-07's masking runs on the result value, before either rendering, so structured content never carries what the text withholds.
- JSON field names are snake_case. Times are RFC 3339.
- Every map field of a result type is `omitempty` or always non-nil. jsonschema-go v0.4.3 types a map as a non-nullable `object` and a slice as nullable (`jsonschema/infer.go:202-222`) [V], so a nil map fails the SDK's output check, and the call becomes a JSON-RPC error instead of a result (`mcp/server.go:464-467`) [V]. Plan 03's `TestResultMapsAreOmitempty` catches it.
- For a metrics result, the text carries the summary and raw points go only in the structured content (ADR-11, plan 05).
- A caveat the text carries for the model, such as plan 04's live-plan label, is in structured content too: some clients pass only one of the two to the model.

## 3. Errors

### 3.1 The envelope

A failing call returns its own result, a nil output and a nil Go error:
- `isError: true`;
- one text content: `error: <code>`, a newline, then the message;
- `_meta`: `{"com.percona/error": {"code": "<code>", "retryable": <bool>}}`;
- no `structuredContent`.

```json
{
  "isError": true,
  "content": [{"type": "text", "text": "error: rate_limited\n<message>"}],
  "_meta": {"com.percona/error": {"code": "rate_limited", "retryable": true}}
}
```

When a per-caller rate limit refused the call (plan 05), `com.percona/error` also carries `retry_after`, in whole seconds, at least 1: `{"code": "rate_limited", "retryable": true, "retry_after": 12}`. The message gives the same wait. A cap on calls in flight sets none (`takeToken`, `errorResult`).

The text keeps today's form (`toolError.Error()`, `errors.go:50-52`) [V]. Today a failure goes back as a Go error, which the SDK turns into an `isError` result with that text and no `_meta` (`tools.go:44-49`, `mcp/server.go:425-434`) [V]; plan 03's `errorResult` adds `_meta` and drops the Go error.

### 3.2 Codes

| Code | Retryable | Meaning | Raised today by [V] |
|---|---|---|---|
| `not_found` | no | The service, query, stored plan, database or table isn't there, or a backing API answered 404 | `engineOf` (`tools_qan.go:681-692`); no QAN data for a `queryid` (`tools_qan.go:348-351`); no stored plan (`tools_actions.go:214-219`); MySQL and MongoDB "not found" errors (`tools_actions.go:515-523`, `:531-532`); HTTP 404 (`errors.go:86-87`) |
| `invalid_input` | no | A value or a combination of arguments is wrong, and the message says what to change; or a backing API answered 400 | the handlers' own checks; MySQL error 1064 on a placeholder fingerprint (`tools_actions.go:177-185`); HTTP 400 (`errors.go:88-89`) |
| `unauthorized` | no | A backing API answered 401 or 403: the token was refused, or its role is too low for that API. PMM's own message is passed on | `errors.go:84-85` |
| `timeout` | yes | A backing call's 30 s limit, the call's action deadline (`PMM_MCP_ACTION_TIMEOUT`), or pmm-agent's own per-action limit passed | `errors.go:95-101`; `deadlineOr` (`tools_actions.go:453-462`); `classifyErrorText` (`tools_actions.go:589-591`) |
| `no_query_source` | no | No stored statement to run the action on | `storedExample` (`tools_actions.go:250-253`) |
| `insufficient_privileges` | no | The monitored database's user lacks a privilege the action needs | `mysqlErrors`, `mongoErrors` (`tools_actions.go:502-533`); `classifyErrorText` (`:581-583`) |
| `agent_unreachable` | yes | No pmm-agent can run the action, or the agent can't reach the database | `mapActionStartError` (`tools_actions.go:490-497`); MySQL errors 1040 and 1203; `classifyErrorText` (`:584-586`) |
| `pmm_unavailable` | yes | A backing API failed in any other way or can't be reached, or PMM's `Metrics` datasource is missing | `errors.go:90-91`, `:103`; `metricsDatasourceUID` (`tools_inventory.go:276-289`) |
| `rate_limited` | yes | A cap on calls in flight, or the caller's rate limit, refused the call before it started (ADR-05; ADR-15 for metric and QAN calls); a rate limit's answer carries `retry_after` | `startLive`, `startLiveOn`, `startMetrics`, `startMetricCall` and `takeToken` (`limits.go`); limits in [§8.1](#81-budgets-of-the-metric-tools) |

- **Retryable** codes are exactly `timeout`, `agent_unreachable`, `pmm_unavailable` and `rate_limited`; a program may repeat such a call unchanged, later. Every other code is not retryable ([§9.2](#92-retryable-codes)).
- **The backing-call codes.** A failed backing call that fails the tool call goes through `mapError` (`errors.go:75-104`) [V], so any tool that makes one can return `not_found`, `invalid_input`, `unauthorized`, `timeout` and `pmm_unavailable`, whatever its own checks add. The rows of [§8](#8-tools) list them with the rest.
- **Messages.** The message says what to do next; `Instructions` tell the model to act on it (`mcp.go:51-54`) [V].
- **No service outside the caller's list.** An error message never names a service outside the caller's service list: every service lookup goes through that list, which plan 06 builds from Access-Role-filtered series (ADR-08). From plan 06, a `service_id` or name outside the list answers `not_found` with a fixed text that echoes nothing the caller sent, "not in your service list (services that sent metrics in the window searched)", followed by the window searched ([spec §8](spec.md#8-phase-3-output-contract) item 4). That window is the call's, at most its last 7 days, and the message says so when it cut a longer one; the last hour for a call without a window; the hour before `at` for `pmm_get_config`; the last 7 days for `pmm_alerts` (plan 07). Today `engineOf` echoes the `service_id` it was given (`tools_qan.go:689`) [V].
- **Redacted messages.** With `PMM_MCP_RAW_SQL` off, an agent error that can quote the statement is withheld and its code is kept (ADR-07; `mapActionError`, `tools_actions.go:550-575`) [V].

### 3.3 Answers outside the envelope

- **Input-schema refusals.** The SDK checks the arguments against the tool's input schema before the handler runs. A refusal is `isError: true` with a text that starts with `validating "arguments": `, and has no `error: <code>`, no `_meta` and no structured content (`mcp/server.go:401-407`) [V]; for example `pmm_top_queries` with `limit: "ten"`. Arguments that pass the schema but don't decode into the input type are refused the same way, with the decoder's message as the text (`mcp/server.go:411-417`) [V]. No tool relies on these refusals for a code: a handler checks values and combinations of inputs itself and answers `invalid_input`. Plan 03's `TestSchemaRefusalShape` pins the shape; a go-sdk upgrade that changes it fails that test, and this section changes with it.
- **An output that fails its own schema** becomes a JSON-RPC error ([§2](#2-one-result-two-renderings)); the map rule and `TestResultMapsAreOmitempty` keep it from happening.
- **HTTP answers before any tool runs:** 401 from nginx `auth_request` for a request without valid credentials, 403 for an anonymous caller or a cross-site `Origin`, and 404 when the endpoint is off or the peer isn't loopback ([spec §4](spec.md#4-architecture), ADR-06, ADR-10).

## 4. Paging

A listing tool takes `limit` and `offset` and returns `page`:

```json
"page": {"total": 312, "offset": 50, "limit": 50, "truncated": true}
```

- `total` counts the items after the tool's filters and narrowing; `offset` is the call's; `truncated` is true when items follow this page: `offset` plus the items returned is less than `total`.
- `page.limit` reports the effective limit: the call's `limit`, or the tool's default when the call passes none or 0. Plan 03 says only that `paginate` treats 0 as the default, and that `pmm_top_queries`' `limit` is the request's, which carries the effective limit to qan-api2 (`tools_qan.go:177`, `:214`) [V]; reporting the effective limit is the reading this document takes [I], for the review to confirm.
- When `truncated`, the text ends with the marker, `showing <offset+1>–<offset+n> of <total>; pass offset=<offset+n> for more`, where `n` is the number of items returned and the dash is an en dash (U+2013): `showing 51–100 of 312; pass offset=100 for more`. A page that isn't truncated has no marker.
- `limit` below 0 or above the tool's maximum, and `offset` below 0, answer `invalid_input`. An `offset` past the end returns an empty page, not an error.
- Plan 03's `paginate` applies these rules to a list MCP holds; `pmm_top_queries` pages in qan-api2 instead ([§9.5](#95-field-rules-other-plans-build-on)).

| Tool | Pages over | Paged by |
|---|---|---|
| `pmm_inventory` | services | MCP, after the `engine` and `node` filters |
| `pmm_top_queries` | report rows | qan-api2 |
| `pmm_get_config` | variables | MCP, after `filter` |
| `pmm_list_metrics` (plan 05) | names or name groups, label names, label values, series | MCP, over what VictoriaMetrics returns with `limit=1001`; more than 1,000 sets `truncated`, with a hint to narrow the search |
| `pmm_alerts` (plan 07) | alerts | MCP, after narrowing and the filters |

Defaults and maximums are in [spec §8](spec.md#8-phase-3-output-contract). Bounded the other way:
- `pmm_get_schema` takes 1 to 10 tables in its input.
- `pmm_query_metrics` returns the top `limit` series by maximum value, with `total_series`, `truncated` and a hint for a narrower query, and has no `offset` (plan 05).
- A plan body and one table's DDL are cut at their caps on a UTF-8 boundary (plan 03's `capText`), with `truncated: true`.
- `pmm_catalog` returns a fixed catalogue, unpaged.

## 5. Provenance

**Window.** A result built from time-based data carries the window it used, in structured content and text:

```json
"window": {"period_from": "2026-11-05T09:00:00Z", "period_to": "2026-11-05T10:00:00Z"}
```

`pmm_top_queries` and `pmm_query_detail` carry it (plan 03), and so do `pmm_service_health` and a range query of `pmm_query_metrics` (plan 05). `pmm_get_config` reads one instant and carries `at` instead.

**`pmm_url`.** A result about a query, service, alert or check carries its "View in PMM" link, the same URL the text shows. The base is PMM's public address setting, else the host the client connected to, else none, and the link is relative (`publicBaseURL`, `links.go:36-56`) [V].

| Result | `pmm_url` |
|---|---|
| `pmm_inventory`, each service | the engine's instance summary dashboard for the service (plan 03's `serviceURL`); plan 06 adds ProxySQL's and HAProxy's |
| `pmm_top_queries` | QAN on the report's window, and on its service when the request names one by `service_name` (`qanOverviewURL`, `tools_qan.go:155`) |
| `pmm_query_detail`, `pmm_get_explain` | QAN with the query selected (`qanQueryURL`, `tools_qan.go:480`; `tools_actions.go:196`, `:226`) |
| `pmm_get_config` | QAN for the service over the hour before `at` (`tools_config.go:135`) |
| `pmm_service_health` (plan 05) | the service's instance summary dashboard (`serviceURL`) |
| `pmm_alerts`, each alert (plan 07) | the alert rule in Grafana's alerting UI, or the alert list when there is no rule UID |

A row of `pmm_top_queries` carries no `pmm_url` of its own: the result's link covers the report (golden file). `pmm_version`, `pmm_catalog`, `pmm_get_schema`, `pmm_query_metrics` and `pmm_list_metrics` carry none.

**`query_ref`.** One query is identified by `queryid`, service and window ([spec §6.1](spec.md#61-resolve-first)), and MCP is stateless, so results hand that identity back:

```json
"query_ref": {"queryid": "<queryid>", "service_id": "<service_id>", "period_from": "2026-11-05T09:00:00Z", "period_to": "2026-11-05T10:00:00Z"}
```

`service_id` is omitted when the result doesn't know it. `pmm_top_queries` (each `group_by=queryid` row) and `pmm_query_detail` return it, under the rules in [§9.5](#95-field-rules-other-plans-build-on). `pmm_get_explain` and `pmm_get_schema` accept it from plan 04 (spec §6.1); plan 03 gives `pmm_get_explain`'s result an optional `query_ref`, and plan 04 gives `pmm_get_schema`'s one.

## 6. Partial results

- **A part** is a backing call whose data the result exists to return.
- **`partial: true`** means at least one part failed and at least one succeeded. When every part fails, the call is an error result ([§3](#3-errors)). Each failed part's error sits next to that part's data as a `partError`, `{"code": "<code>", "message": "<message>"}`, built through `mapError` (`partErrorOf`); its retryability is its code's ([§3.2](#32-codes)).
- **Best-effort enrichment is not a part:** a service's `version` (`serviceVersion`, `enrichVersions`), and `pmm_top_queries`' engine lookup for quoting (`reportEngines`). When enrichment fails, its field is left out, or the fail-closed rule withholds the fingerprint (ADR-07), and `partial` doesn't change. Plan 03's list names only these two. This document reads `pmm_inventory`'s node names the same way [I]: they come from a call of their own that is best effort today, and when it fails, the node names are empty (`nodeNames`, `tools_inventory.go:185-193`) [V]. Plan 06 takes them from the same series as the services (ADR-08).

| Tool | Parts | Each part's error | Today [V] |
|---|---|---|---|
| `pmm_query_detail` | `POST /v1/qan:getMetrics` and `POST /v1/qan/query:getExample` | `metrics_error`, `example_error`; the text adds a line naming the failed part and its code | one failure is tolerated silently; both fail the call (`tools_qan.go:375-411`) |
| `pmm_get_schema` | the DDL action and the index action of each table | `tables[].definition_error`, `tables[].indexes_error` | a failed action shows its error in its table's block; all failing fails the call (`tools_actions.go:357-359`, `:392-404`) |
| `pmm_service_health` (plan 05) | each signal's query | `signals[].error` | — |

Plan 07 gives `pmm_alerts` no `partial` field: a failing service list fails the call, so it never returns un-narrowed results.

## 7. Untrusted fields

- A field whose text comes from a monitored database or from a user has an output-schema description, the field's `jsonschema` text, that starts with `Untrusted.`.
- The kinds: fingerprints, query examples, plans, DDL, label and dimension values, variable values, service, node, database, schema and table names, `environment`, `cluster` and `address` values, `version` strings, and the `message` of a part's error (plan 03, plan 06); alert names, severities, labels, summaries and descriptions (ADR-11, ADR-17, plan 07).
- Claude Code doesn't send output schemas to the model (measured 2026-11-06), so the marks don't reach the model there. `Instructions` are the channel that does: they name every kind of untrusted text as data, not instructions, and each plan that adds a kind extends that list (plan 04: QAN dimension values, `environment` and `cluster`; plan 07: alert names, labels, summaries and descriptions, and the links in them). The marks stay for clients that read output schemas ([spec §8](spec.md#8-phase-3-output-contract) item 6).
- Either way it is advice to the model: it doesn't make injected text harmless (ADR-11), and what bounds the harm is that every tool is read-only (ADR-05). `mcp.md` warns against combining `/mcp` with unattended tools that can send data out of the client (plan 04).
- The mark is not redaction. ADR-07 decides what is masked: with `PMM_MCP_RAW_SQL` off, fingerprints, examples and plans are masked or withheld; DDL, names, dimension and label values, variable values, `version` strings, part error messages, and alert texts are returned as stored.

| Tool | Untrusted fields |
|---|---|
| `pmm_version` | none |
| `pmm_inventory` | `services[].service_name`, `services[].node_name`, `services[].version`, `services[].address`; plan 06 adds `services[].environment`, `services[].cluster` and removes `services[].address` |
| `pmm_top_queries` | `rows[].fingerprint`, `rows[].dimension` |
| `pmm_query_detail` | `service_name`, `version`, `database`, `schema`, `fingerprint`, `example`, `tables`, `metrics_error.message`, `example_error.message` |
| `pmm_get_explain` | `service_name`, `plan` |
| `pmm_get_schema` | `tables[].database`, `tables[].name`, `tables[].definition`, `tables[].indexes`, `tables[].definition_error.message`, `tables[].indexes_error.message`; plan 04 adds `unresolved`, `not_fetched` |
| `pmm_get_config` | `service_name`, `version`, `variables[].value` |
| `pmm_catalog` | none |
| `pmm_service_health` (plan 05) | `service_name`, `signals[].error.message` |
| `pmm_query_metrics` (plan 05) | `series[].labels`, `shared_labels` |
| `pmm_list_metrics` (plan 05) | `labels`, `values`, `series` |
| `pmm_alerts` (plan 07) | `alerts[].name`, `alerts[].severity`, `alerts[].labels`, `alerts[].summary`, `alerts[].description` |

Plan 03's `TestUntrustedFieldsMarked` holds this list, with an empty entry for a tool that has no such field. It and the other contract tests keep a list keyed by tool name and fail when a tool in `tools/list` has no entry, so a new tool can't skip them.

## 8. Tools

The rows of the tools that exist describe them at `911910199` with plan 03's changes; where plans 04 and 06 change a row, the cell says so. The rows of planned tools are the design in their ADRs and plans; a cell those don't settle says so, marked [I]. The codes column lists every code a tool can return, in the order of `errors.go`, the backing-call codes included ([§3.2](#32-codes)); for a planned tool, those come from `mapError`, which its calls go through [I]. After the triage on a Feature Build, plan 08 records in the engines column what each tool returns per engine (spec §11).

**Access Roles** (ADR-03). *Filtered:* the backing API applies the caller's Access Roles. *Narrowed:* MCP drops what is outside the caller's service list, the services in the `up` series the caller can read (ADR-08). Narrowing makes MCP's results consistent with the caller's other data; it is not a security boundary.

**Minimum role** is the Grafana role. `/mcp` itself needs Viewer (`managed/services/grafana/auth_server.go:132`) [V].

**Invariant** (ADR-10). A tool returns only public data, such as `pmm_catalog`'s reference data, unless a backing call authorized it with the caller's headers. A token goes to every backing call as `Authorization: Bearer <token>` with no `Cookie`; Basic credentials and a cookie go unchanged (plan 06).

| Tool | Minimum role | Backing API | Access Roles | Kind | Engines | Error codes |
|---|---|---|---|---|---|---|
| `pmm_version` | Viewer | `GET /v1/server/version` | none: no service data | Passive | — | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `pmm_unavailable` |
| `pmm_inventory` | Viewer | `GET /v1/inventory/services`, `GET /v1/inventory/nodes`; version metrics through the Grafana datasource proxy. Plan 06: the `up` series through the datasource proxy | Today neither: the inventory API applies no Access Role filter. Plan 06: the caller's service list itself, from series vmproxy filters | Passive | MySQL, PostgreSQL, MongoDB. Plan 06: every service type in the list | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `pmm_unavailable` |
| `pmm_top_queries` | Viewer | `POST /v1/qan/metrics:getReport`; for fingerprint quoting, `POST /v1/qan/metrics:getFilters`, a second `getReport` and `GET /v1/inventory/services`; from plan 03, the caller's service list for a `query_ref` pinned by `service_name`. Plan 06: the caller's service list instead of `GET /v1/inventory/services` | Filtered by qan-api2; not narrowed | Passive | MySQL, PostgreSQL, MongoDB: what QAN collects | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `pmm_unavailable`; from plan 05, `rate_limited` |
| `pmm_query_detail` | Viewer | `POST /v1/qan:getMetrics`, `POST /v1/qan/query:getExample`; version metrics | Filtered by qan-api2. Plan 04: also narrowed | Passive | MySQL, PostgreSQL, MongoDB | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `pmm_unavailable`; from plan 05, `rate_limited` |
| `pmm_get_explain` | Viewer | `GET /v1/inventory/services` (plan 06: the caller's service list); to resolve a `queryid` to one service, `POST /v1/qan/metrics:getReport`, `POST /v1/qan:getMetrics` and `POST /v1/qan/query:getExample`. PostgreSQL: `GET /v1/qan/query/{queryid}/plan`. MySQL and MongoDB: `POST /v1/actions:startServiceAction`, `GET /v1/actions/{action_id}`, `POST /v1/actions:cancelAction` | Narrowed: the service is looked up in the caller's list before any plan is fetched (plans 04 and 06). The actions API is not filtered; the stored plan is, by qan-api2 | PostgreSQL passive; MySQL and MongoDB live | MySQL: a live non-executing `EXPLAIN`, JSON or traditional. PostgreSQL: `pg_stat_monitor`'s stored plan. MongoDB: a live `explain` of the stored example; the tool has no `query` input | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `no_query_source`, `insufficient_privileges`, `agent_unreachable`, `pmm_unavailable`, `rate_limited` |
| `pmm_get_schema` | Viewer | `GET /v1/inventory/services` (plan 06: the caller's service list); `POST /v1/actions:startServiceAction`, `GET /v1/actions/{action_id}`, `POST /v1/actions:cancelAction`; with a `query_ref` or `queryid`, also `POST /v1/qan/metrics:getReport`, `POST /v1/qan:getMetrics` and `POST /v1/qan/query:getExample` | Narrowed, as `pmm_get_explain`; the actions API is not filtered | Live | MySQL: `SHOW CREATE TABLE` and `SHOW INDEX`. PostgreSQL: the table definition and its indexes. MongoDB: `invalid_input` | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `insufficient_privileges`, `agent_unreachable`, `pmm_unavailable`, `rate_limited` |
| `pmm_get_config` | Viewer | `GET /v1/inventory/services` (with `service_id`; plan 06: the caller's service list, for `service_name` too); `GET /graph/api/datasources/name/Metrics`; the datasource proxy's `/api/v1/query` | Filtered by vmproxy; a `service_id` is narrowed. Plan 06: a `service_name` too | Passive | MySQL (`mysql_global_variables_*`) and PostgreSQL (`pg_settings_*`): numeric variables only. MongoDB: `invalid_input` | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `pmm_unavailable` |
| `pmm_catalog` (plan 03; `metrics` kind plan 05) | Viewer | none: built into pmm-managed | none: reference data | Passive | `qan_columns`: MySQL, PostgreSQL, MongoDB. `metrics` (plan 05): MySQL, PostgreSQL, MongoDB, node | `invalid_input` |
| `pmm_service_health` (plan 05) | Viewer | the caller's service list; `GET /graph/api/datasources/name/Metrics`; the datasource proxy's `/api/v1/query_range` | Filtered by vmproxy; the service is narrowed | Passive | MySQL, PostgreSQL, MongoDB, each with its node's signals | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `pmm_unavailable`, `rate_limited` |
| `pmm_query_metrics` (plan 05) | Viewer | `GET /graph/api/datasources/name/Metrics`; the datasource proxy's `/api/v1/query`, `/api/v1/query_range` and, for the series cap, `/api/v1/series` | Filtered by vmproxy | Passive | any metric PMM holds | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `pmm_unavailable`, `rate_limited` |
| `pmm_list_metrics` (plan 05) | Viewer | `GET /graph/api/datasources/name/Metrics`; the datasource proxy's `/api/v1/label/__name__/values`, `/api/v1/labels`, `/api/v1/label/{name}/values`, `/api/v1/series` | Filtered by vmproxy | Passive | any metric PMM holds | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `pmm_unavailable`, `rate_limited` |
| `pmm_alerts` (planned, plan 07) | Viewer | Grafana's rules API, `GET /graph/api/prometheus/grafana/api/v1/rules`; for silence state, the Alertmanager's alerts and silences under `/graph/api/alertmanager/grafana/api/v2/`, joined by rule UID and label set; the caller's service list over 7 days | Narrowed, not filtered: no Grafana alerting API applies an Access Role filter. The rules API is folder-scoped, so a Viewer gets what PMM's alert page shows (ADR-17) | Passive | any service type, nodes, and server-level alerts | `not_found`, `invalid_input`, `unauthorized`, `timeout`, `pmm_unavailable` |

`pmm_advisors`, planned for plan 07, is out of the Tech Preview ([ADR-18](adr/ADR-18-advisors.md)).

Notes, tool by tool. Line numbers are in `managed/services/mcp/` unless a path says otherwise.

- **Roles of the existing tools** [V]: `/v1/server/version` (`auth_server.go:114`), `/v1/qan` (`:116-117`) and `/v1/actions` (`:87-88`) are Viewer, and `GET /v1/inventory/services` and `/nodes` are Viewer through #5942's rules (`:166-167`), which plan 06 removes (ADR-08). `/graph` needs no role in PMM's auth server (`:124`), so Grafana's own checks apply to the datasource calls; `mcp.md` documents Viewer for every existing tool (`documentation/docs/api/mcp.md:194-195`), and the reference triage runs with a Viewer token (spec §1.4, §11). After plan 06 a Viewer token still covers every tool (ADR-08).
- **Filtering of the existing tools** [V]: `/v1/qan/`, `/v1/qan:` and `/graph/api/datasources/` are in `lbacPrefixes` (`auth_server.go:181-197`); `/v1/inventory` and `/v1/actions` are not. qan-api2 applies the caller's filters to query details, examples and stored plans (PMM-15697, `a98506570`, merged into `PMM-MCP-GA` with `main`; `qan-api2/models/metrics_lbac_test.go`), and its plan endpoint honours the `service_id` MCP sends (`qan-api2/models/metrics.go:952-974`, `client.go:290-297`). Until plan 06, the caller's service list is the whole inventory (`listServices`, `tools_inventory.go:146-183`), so the narrowing of `pmm_get_explain`, `pmm_get_schema` and `pmm_get_config` removes nothing yet.
- **`pmm_version`.** No checks of its own. Plan 03's test pins `not_found` for a missing route.
- **`pmm_inventory`.** `invalid_input`: an `engine` other than `mysql`, `postgresql` or `mongodb` (`tools_inventory.go:100-102`); `limit` and `offset` (plan 03). Plan 06 drops `address` and `port` and adds `node_id`, `environment`, `cluster` and `last_seen` (ADR-08, plan 06 Task 1); its `engine` filter takes every PMM service type: `mysql`, `postgresql`, `mongodb`, `proxysql`, `haproxy`, `valkey`, `external`.
- **`pmm_top_queries`.** `invalid_input`: the window; `group_by`; `limit` (1 to 100), `offset`; `search` (200 characters); `columns` (10 at most, known names; from plan 03 the message points to `pmm_catalog`); `order_by`; `labels` names, values, a quote or backslash in a value, and shortcuts that disagree with `labels` (`tools_qan.go:116-123`, `:172-285`, `:484-490`). A service QAN shows but the caller's list lacks appears here and answers `not_found` from detail, explain and schema ([spec §9.2](spec.md#92-the-callers-service-list)). From plan 05, `rate_limited`: the metric-call caps, which QAN calls share; and `invalid_input` for a window over 30 days.
- **`pmm_query_detail`.** `invalid_input`: `queryid` empty; a quote or backslash in `queryid` or `service_id`; the window (`tools_qan.go:331-341`). `not_found`: neither QAN call returned data (`:348-351`). From plan 04, a `service_id` outside the caller's list is `not_found`, and without one, QAN rows of services outside the list are dropped (spec §6.1). From plan 05, `rate_limited` and the 30-day window, as `pmm_top_queries`.
- **`pmm_get_explain`.** The query is `query_ref`, or `queryid` with optional `service_id`, `period_from` and `period_to`; the tool has no `query` input. `invalid_input`: neither `query_ref` nor `queryid`; `query_ref` beside `queryid`, `service_id` or a period; a `query_ref` without `queryid`, `period_from` or `period_to`; a quote or backslash in `queryid` or `service_id`; `format`; a queryid seen on several services in the caller's list (the message lists them); a service of another engine, "EXPLAIN is not available for engine"; MySQL error 1064 on a placeholder fingerprint, with a message asking for `placeholders` and `database`; a query QAN stored trimmed, and a MongoDB write or admin operation (`refFromInput`, `resolveQuery`, `explain`, `mysqlExplainError`, `mongoErrors` in `resolve.go` and `tools_actions.go`). `not_found`: a `service_id` outside the caller's list, with the fixed text; a queryid not seen on any of the caller's services in the window, the message naming the window; no stored PostgreSQL plan; a missing database or table, from the action. `no_query_source`: a MongoDB query with no stored example in the window. `rate_limited`, `insufficient_privileges` and `agent_unreachable` come from the live path, MySQL and MongoDB only; `rate_limited` is also the answer when the service already has a live call in flight on the replica. One `PMM_MCP_ACTION_TIMEOUT` bounds the call, lookups included. A plan body is capped (spec §8). A live plan carries `live: true` and a `note` that it is the plan the database would choose now, in text and in structured content (spec §6.1, §6.3).
- **`pmm_get_schema`.** Tables are named with `service_id`, `database` and `tables`, or fetched for a query with `query_ref` or `queryid` (the same resolution as `pmm_get_explain`, with optional `placeholders` for MySQL). `invalid_input`: `info_types`; `tables` (1 to 10 non-empty names); the two forms mixed: `database` or `tables` with a query form, `placeholders` or a period without one; `service_id`, `database` or `tables` missing in the named form; a MongoDB service; a MySQL query without a stored example, asking for `placeholders`. `not_found`: a service outside the caller's list, or a missing database or table. `no_query_source`: a PostgreSQL query whose QAN record has no tables. `rate_limited` comes after the service lookup, and in the query form after the query is resolved; it is also the answer when the service already has a live call in flight on the replica. DDL is not masked (ADR-07). Each table's DDL is capped (spec §8). A MySQL query's tables come from one live `EXPLAIN`: names the plan doesn't tie to a table are `unresolved`, and tables beyond 10 are `not_fetched`.
- **`pmm_get_config`.** `invalid_input`: neither `service_id` nor `service_name`; `engine`; `at`; a service that is neither MySQL nor PostgreSQL (`tools_config.go:55-94`); `limit` and `offset` (plan 03). `pmm_unavailable` also when the `Metrics` datasource is missing or not Prometheus-typed (`tools_inventory.go:276-289`). Today a `service_name` without `service_id` is not looked up (`tools_config.go:74-84`) [V]; plan 06 resolves it through the caller's list over the hour before `at`, and a name outside it is `not_found` with the fixed text. String settings are not in metrics ([spec §6.4](spec.md#64-pmm_get_config-beyond-numeric-variables)).
- **`pmm_catalog`.** Kinds: `qan_columns` (plan 03), `metrics` (plan 05). The optional `engine` filter applies to every kind: `mysql`, `postgresql` or `mongodb`, and `node` for `metrics` only. For `qan_columns` it keeps that engine's entries plus the all-engine ones; for `metrics`, that engine's metrics. `invalid_input`: an unknown `kind`, listing the kinds; an `engine` outside the kind's list, naming the list, so `engine: node` with `kind: qan_columns` is refused (`catalog`, `tools_catalog.go`).
- **`pmm_service_health`** (plan 05 Task 7; `tools_health.go`). `not_found`: a `service_id` outside the caller's list. `invalid_input`: the window, or a window too long for the execution budget, before any query. The window is under 7 days at most, because each signal also reads about 5 minutes before it and a call reads at most 7 days; the message names the longest window that fits (`checkHealthWindow`). `rate_limited`: the call holds one slot of the metric-call caps and one token of the metric rate. A failing signal sets its `error` and `partial`; when every signal fails, the call fails with the first error, so any of the codes above. `note` joins these sentences, each once: when every signal is `no_data`, one saying an Access Role may hide the series of the service and its node, in place of the next; when a node signal is `no_data` and others are not, one saying an Access Role that filters on service labels may hide the node's series (ADR-15); one for null values, which are NaN or infinite; one per signal that returned several series, naming how many; and one when the service's node name is unknown, so the node signals were not queried. From plan 06, a service that an Access Role hides is outside the list and answers `not_found`; the sentence for every signal `no_data` then says that the listed service sent none of these metrics in the window, and that an Access Role can still hide its node's series. A listed service that is neither MySQL, PostgreSQL nor MongoDB answers `invalid_input`.
- **`pmm_query_metrics`** (plan 05 Task 4). `invalid_input`: an expression the execution budget refuses, with a hint, before any request ([§8.1](#81-budgets-of-the-metric-tools)); a selector over the series cap; `limit` outside 1 to 100; `time` beside a period; `step` on an instant query, or not a positive whole number of seconds, or one the caller gave that is too small for a rollup over an expression (the hint names the smallest); a response over the read cap; VictoriaMetrics answering 422, with its message. `rate_limited`: the metric-call caps and the metric rate.
- **`pmm_list_metrics`** (plan 05 Task 5). `invalid_input`: an unknown `kind` or an input the `kind` doesn't take; `match` missing for `series`; a `label` outside the label-name grammar; a look-back over 7 days; a `match` selector the execution budget refuses, with a lookbehind of 0; `limit` and `offset`; a response over the read cap, for a selector the caller wrote. `rate_limited`: the metric-call caps and the metric rate.
- **`pmm_alerts`** (plan 07 Task 2). `not_found`: a `service_id`, `service_name` or `node_name` filter outside the 7-day list, with the fixed text. `unauthorized`: Grafana answers 401. `invalid_input`: `limit` and `offset` (`paginate`). Every result, an empty one included, says "Currently firing alerts only; resolved alerts are not shown." (ADR-17). The narrowing rule is ADR-17's.

### 8.1 Budgets of the metric tools

Values are spec §8's; the rules below are what `checkExpr` (`metrics_check.go`), `shapeSeries` (`metrics_budget.go`), `client.go` and `limits.go` enforce, and `documentation/docs/api/mcp.md` documents.

**Execution budget.** Checked on the parsed expression of `pmm_query_metrics`, of each `pmm_service_health` signal for the window, and of each `match` selector of `pmm_list_metrics` (a lookbehind of 0). Every refusal is `invalid_input` with a hint, before any request:
- **Size.** At most 4 KiB.
- **Selectors.** At most 10; each `or` group inside braces counts as one.
- **Metric name.** Every selector names a metric: `__name__` with `=`, or with `=~` and a regular expression that starts with at least 3 literal bytes.
- **Scope.** A selector that matches the name with a regular expression also has a `service_id`, `service_name`, `node_id` or `node_name` matcher, either `=` or `=~` with only literal `|`-separated alternatives: `db1|db2` and `db\.prod` are scopes; `.+` and `db.prod` are not.
- **Time read.** At most 7 days. The time read is the query's range plus the largest lookbehind of any path from the query to a selector; an instant query has a range of 0. A path's lookbehind sums, as VictoriaMetrics reads them, the window of each rollup; the range of each subquery plus two of its own steps and 5 minutes; and the absolute value of each `offset`. A selector read through no window (`up`, or `rate(x)` written without one) reads one step back; an instant query's step is 5 minutes; a window shorter than the step counts as one step.
- **`@`** is refused, since it reads outside the query's time range.
- **Templates.** A MetricsQL `WITH` template and the built-in templates `ttf`, `ru`, `range_median` and `alias` are refused, because they expand before the checks run.
- **Series per value.** Functions that create a series for each distinct value, or whose output no budget bounds, are refused: `count_values`, `count_values_over_time`, `histogram` and `histogram_over_time`, and `aggr_over_time` when a string argument names one of them.
- **Characters.** A non-ASCII character or a backslash outside a quoted string is refused.
- **Subquery step.** A subquery's step is at least the time read ÷ 2,000; a subquery without a step takes the query's step and is checked the same way.
- **Implicit subqueries.** A rollup over something that is not a selector, such as `rate(sum(x)[1h])`, runs in VictoriaMetrics as a subquery at the query's step, limited to 4,000 points per series. Without a `step` the server raises it to what the rollup needs; a `step` the caller gave that is too small is refused, and the hint names the smallest.
- **Instant range.** An instant `pmm_query_metrics` query whose root is a range selector or a subquery (`x[5m]`, `x[1h:1m]`, `x[:1m]`), with or without `offset`, is refused: VictoriaMetrics would answer with a range of samples.

**Series cap.** Before a `pmm_query_metrics` query runs, each selector is counted over the time read with the `series` endpoint and `limit=2001`; a selector matching more than 2,000 series refuses the query.

**Response budget** of `pmm_query_metrics`:
- at most `limit` series, 20 by default and 100 at most, the largest by maximum;
- at most 2,000 points in all, and 16 KiB for the text and the structured content together;
- when the points don't fit in either, every series carries a summary (`min`, `avg`, `max`, `last`, `last_at`) and `summarized` is true; when summaries are still over 16 KiB, fewer series are kept, `truncated` is true, and the hint says how many were left out;
- when the query alone takes up the 16 KiB, for example because JSON writes each `<`, `>` and `&` as six bytes, `query` holds only its first 200 bytes;
- NaN and infinite values are `null`, left out of `min`, `avg` and `max`, with a count in `note`;
- the labels `agent_id`, `agent_type`, `node_id`, `machine_id`, `instance` and `job` are dropped, and a label equal on every series shown moves to `shared_labels`.

**Read cap.** MCP reads at most 4 MiB of any datasource-proxy response. A longer one fails the call: `invalid_input` with a hint to narrow, for an expression or selector a caller wrote, and `pmm_unavailable` otherwise.

**Limits on calls and requests.** Callers are told apart by a hash of the credential; replicas are pmm-managed instances.

| Limit | Applies to | Value |
|---|---|---|
| Metric and QAN calls in flight, per caller | `pmm_query_metrics`, `pmm_list_metrics`, `pmm_service_health`, `pmm_top_queries`, `pmm_query_detail` | 4 |
| Metric and QAN calls in flight, per replica | the same | 8 |
| Metric call rate, per caller | `pmm_query_metrics`, `pmm_list_metrics`, `pmm_service_health` | 60 a minute, burst 10 |
| Live calls in flight, per caller, per replica, per service and replica | `pmm_get_explain` (MySQL, MongoDB), `pmm_get_schema` | 2, 8, 1 |
| Live call rate, per caller | the same | 10 a minute, burst 4 |
| Requests to VictoriaMetrics in flight, per replica | every request MCP sends, from any tool | half of VictoriaMetrics' concurrent-query limit, at least 1 |

- A call of a metric tool counts once, however many queries it runs.
- The concurrent-query limit is `VM_search_maxConcurrentRequests` when it is set, else VictoriaMetrics' own default, `min(2 × CPUs, 16)` (v1.154.0); PMM doesn't set `-search.maxConcurrentRequests`.
- A request waits for a slot until its call's deadline, then fails with `timeout`.
- A call refused for its rate is `rate_limited` with `retry_after`; one refused for calls in flight is `rate_limited` without it.

**QAN window.** `pmm_top_queries` and `pmm_query_detail` read at most 30 days; a longer window is `invalid_input`, before any QAN call.

## 9. Decisions recorded here

### 9.1 Advisors disabled

Kept for a later ticket: `pmm_advisors` is out of the Tech Preview ([ADR-18](adr/ADR-18-advisors.md)), so nothing builds this now.

`pmm_advisors` answers `invalid_input` with the message "Advisors are disabled in PMM's settings", never an empty list, which would read as "no failed checks".
- When Advisors are disabled, `GET /v1/advisors/checks/failed` answers FailedPrecondition (`managed/services/management/checks.go:120-121`) [V]. grpc-gateway v2.33.0 sends FailedPrecondition as HTTP 400 (`runtime/errors.go:58-60`) [V], and `mapError` maps 400 to `invalid_input` (`errors.go:88-89`) [V].
- MCP sends that request with no parameters (ADR-18, option 2), and the only parameters the API validates are the paging ones (`api/advisors/v1/advisors.proto:148-155`) [V], so a 400 from it means Advisors are disabled, and the tool replaces the message.
- The ticket that builds `pmm_advisors` tests it, with a fixture and on a live server.

### 9.2 Retryable codes

`retryable` is true for exactly `timeout`, `agent_unreachable`, `pmm_unavailable` and `rate_limited`, and false for every other code (ADR-11). Plan 03's `TestRetryable` pins the list.

### 9.3 The `partial` rule

As [§6](#6-partial-results): `partial` means at least one part failed and at least one succeeded; when every part fails, the call is an error result; best-effort enrichment is not a part, and its failure doesn't change `partial`.

### 9.4 The paging marker

As [§4](#4-paging): `showing <offset+1>–<offset+n> of <total>; pass offset=<offset+n> for more`, at the end of the text, only when `truncated`.

### 9.5 Field rules other plans build on

- **`queryRow.rank`** is the row's position in the whole report, 1-based, offset included: the number the text shows (`tools_qan.go:144`) [V]. It is not qan-api2's `rank` (`deps.go:122`).
- **`query_ref.service_id` in `pmm_top_queries`.** `query_ref` is set on `group_by=queryid` rows, with the request's window. Its `service_id` is set when the request pins one service: by `service_id`, by one `labels.service_id` value, or by one `service_name` (or `labels.service_name`) value, looked up in the caller's service list with one `listServices` call, made only then. Otherwise `service_id` is omitted, and plan 04 resolves the `queryid` from QAN's candidates: one is used; several answer `invalid_input` listing them ([spec §6.6](spec.md#66-acceptance)).
- **`query_ref.service_id` in `pmm_query_detail`** comes from the stored example's `service_id`, else from the `qan:getMetrics` metadata.
- **`page` in `pmm_top_queries`.** `total` is the report's `total_rows`; `offset` and `limit` are the request's; `truncated` is `offset + len(rows) < total`. The text keeps its `Rows a-b of n` header (`tools_qan.go:153-154`) and ends with the marker when truncated. Paging stays qan-api2's: MCP doesn't page the rows again.
- **`tableResult`'s per-part errors.** A table's DDL action and index action fail independently, and each failure goes in its own field, `definition_error` or `indexes_error`, omitted otherwise. `truncated` is true when either text was cut. `schemaResult.partial` follows [§6](#6-partial-results), over all the actions of the call.

The other field rules of plan 03 Task 5, for reference:
- `load`, `calls`, `query_time_total` and `query_time_avg` are the values the text prints as `load`, `calls`, `total` and `avg`, with the same fallbacks; times in seconds (`renderRow`, `tools_qan.go:289-305`).
- `columns` has one entry per requested column the row has, keyed by the column's name as `pmm_catalog` lists it: the `avg` statistic for a column whose aggregation is `avg`, else the `sum`. The base columns `load`, `num_queries` and `query_time` are not repeated.
- `pmm_query_detail`'s `metrics` holds the pairs the text prints, under the same names (`calls`, `query_time_sum`, `query_time_avg`, `rows_examined_avg`, …), zero-skipping included (`keyMetrics`, `tools_qan.go:625-660`).

### 9.6 Untrusted marks on names

Service, node, database, schema and table names, `environment`, `cluster` and `address` values, `version` strings, and part error messages are marked untrusted ([§7](#7-untrusted-fields)), as are alert severities.
- Plan 03's rule marks a field whose text comes from a monitored database or a user, and these fields do. Database, schema and table names come from the monitored database, like DDL. Service and node names, `environment`, `cluster` and `address` are typed in by whoever registers the service. A `version` is the string the monitored server reports, read from the exporters' info metrics. A part's error message can quote the monitored database's own error text. An alert's `severity` label is set by the rule's author.
- The field lists of [§7](#7-untrusted-fields) and the plans follow the rule: every field named there, and the same fields in the plans' result types, is marked.
- IDs, engine values, codes, `pmm_url`, numbers and timestamps are PMM's own and stay unmarked.

## 10. Question for the review

1. **`version` when enrichment fails.** Plan 03 leaves an enrichment field out when it fails ([§6](#6-partial-results)). `pmm_inventory` prints `unknown` today (`tools_inventory.go:249-251`) [V], and plan 03 Task 4 gives `serviceRow.version` no `omitempty`. Choose `unknown` or an omitted `version`, and apply the same to `pmm_query_detail` and `pmm_get_config`.
