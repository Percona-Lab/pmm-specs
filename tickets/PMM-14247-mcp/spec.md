# MCP endpoint in PMM Server: analysis and design (PMM-14247)

- **Date:** 2026-10-22, revised 2026-10-24 and 2026-10-26 after the first and second reviews of [#4](https://github.com/Percona-Lab/pmm-specs/pull/4).
- **Epic:** [PMM-14247](https://perconadev.atlassian.net/browse/PMM-14247), phases PMM-15527 to PMM-15532 ([§2](#2-sources)).
- **Code base:** percona/pmm branch `PMM-MCP-GA` at `826945906`, and the phase 2 branches listed in [§3](#3-where-the-work-stands). Line numbers refer to those commits; re-check them before you edit.
- **Plans that implement this document:** `plans/00-roadmap.md` and the plans next to it, added once this document is reviewed.

Marks used below:
- **[V]** means verified by reading the code, the ticket or the pull request.
- **[I]** means inferred, or taken from upstream documentation, and not run.

MCP here is the [Model Context Protocol](https://modelcontextprotocol.io).

---

## 1. Summary

**What gets built.** One read-only MCP tool layer inside pmm-managed, served at `https://<pmm-server>/mcp` over MCP Streamable HTTP. The tools cover query triage (QAN, EXPLAIN, schema, configuration), metrics, firing alerts and Advisor results. Any MCP client (Claude Code, Cursor, a customer's own agent) drives it with an ordinary PMM service-account token. Every tool call goes back out through PMM's public REST API on the nginx loopback with the caller's own credentials, so the MCP layer can never do more than the same token can do with `curl`.

**Where it stands.** Phases 0 and 1 are merged into the integration branch `PMM-MCP-GA`. Phase 2 is partly written on three stacked branches. Phases 2b to 5 have not started ([§3](#3-where-the-work-stands)).

**What this document adds.**
- It records the decisions already implemented as ADR-01 to ADR-10. They were taken in the epic, in pull requests and in `managed/services/mcp/DECISIONS.md`, but none had an architect review, so all start as **Proposed** ([§5](#5-decisions-already-taken)). The first review revised three of them: live inspection gets a per-caller limit (ADR-05), inventory reads apply Access Roles (ADR-08), and `/mcp` checks `Origin` (ADR-10).
- It designs the rest of phase 2 ([§6](#6-phase-2-the-rest-of-query-intelligence)), metrics, alerts and Advisors (phase 2b, ADR-15, ADR-17, ADR-18, [§7](#7-phase-2b-metrics-alerts-and-advisors)), the output contract (phase 3, ADR-11, [§8](#8-phase-3-output-contract)), identity and Access Roles on PMM's service-scoped APIs (phase 4, ADR-12, ADR-16, ADR-08, [§9](#9-phase-4-identity-and-access-roles)), and the release (phase 5, ADR-14, [§10](#10-phase-5-release)). Access-Role permissions (ADR-13) move to PMM-15791, after the MCP release.
- It sets the order of the remaining work ([§3.1](#31-order-from-here)) and corrects the phase tickets where they are wrong or outdated ([§12](#12-corrections-to-the-tickets)).

**Where the design material lives.** From now on, here. `DECISIONS.md` and `dev/docs/managed/mcp-access-roles-proposal.md` move from `PMM-MCP-GA` into the ADRs; a later `PMM-MCP-GA` pull request replaces them with a pointer to this folder. The tool contract (phase 3) and the identity design (phase 4), which the tickets place in percona/pmm `dev/docs/managed/`, are written here instead.

---

## 2. Sources

- **Epic** PMM-14247, read in full [V]. It holds the problem statement, the architecture decisions, the phase table and the acceptance criteria.
- **Phase tickets**, read in full [V]: PMM-15527 (phase 0, unblock and cut the branch), PMM-15528 (phase 1, harden), PMM-15529 (phase 2, query intelligence), PMM-15530 (phase 3, output contract), PMM-15531 (phase 4, identity), PMM-15532 (phase 5, land and productize).
- **Related tickets outside the epic** [V]: PMM-15533 (Done), PMM-15534, PMM-15535, PMM-15536. **Children filed later** [V]: PMM-15702, PMM-15703. **Filed with this spec:** PMM-15790 (phase 2b), PMM-15791 (ADR-13), PMM-15792 (§6.4). **Referenced from the code:** PMM-15697, PMM-15715.
- **Pull requests in percona/pmm** [V]:
  - [#5942](https://github.com/percona/pmm/pull/5942): the base implementation, contributed by Sixta Systems. Merged into `PMM-MCP-GA` on 2026-09-21. Its only review is CodeRabbit's.
  - [#6068](https://github.com/percona/pmm/pull/6068): phase 1. Merged into `PMM-MCP-GA` on 2026-10-20, with one human approval.
  - [#6099](https://github.com/percona/pmm/pull/6099): phase 2, QAN column catalogue. Open.
  - [#4045](https://github.com/percona/pmm/pull/4045): Percona's earlier in-server attempt with an AI chat backend. Closed unmerged. Source of the query intelligence ported in phase 2; head `3032de7e1`.
- **percona/pmm-mcp**: a standalone MCP server. Empty apart from a README, with two contributor pull requests open since June and August 2026 (epic).
- **Design files on `PMM-MCP-GA`** [V]: `managed/services/mcp/DECISIONS.md` (D1 to D10 and implementation notes) and `dev/docs/managed/mcp-access-roles-proposal.md`.
- **Go SDK** `github.com/modelcontextprotocol/go-sdk` v1.8.0 (from `go.mod`), source read for the structured-output behaviour [V].
- **How Access Roles are applied today** [V]: vmproxy (`vmproxy/proxy/proxy.go`), qan-api2 (`qan-api2/models/reporter.go`), and in pmm-managed the auth server, the Advisors API (`managed/services/management/checks.go`) and the Grafana client.
- **percona/grafana**, `pkg/services/serviceaccounts/api/token.go` and `models.go`, read for the service-account response [V].

---

## 3. Where the work stands

As of 2026-10-22 [V]:

| Phase | Ticket | Jira | Code |
|---|---|---|---|
| 0 Unblock, cut `PMM-MCP-GA` | PMM-15527 | In Progress | Branch exists; #5942 merged into it. The CLA, the security-review booking and the contributor replies were not checked. |
| 1 Harden | PMM-15528 | In Progress | #6068 merged into `PMM-MCP-GA`. |
| 2 Query intelligence | PMM-15529 | In Progress | See below. |
| 2b Metrics, alerts and Advisors | PMM-15790 | Open | Not started. |
| 3 Output contract | PMM-15530 | Open | Not started. An `Instructions` block already exists (`mcp.go:37`). |
| 4 Identity and Access Roles | PMM-15531 | Open | Not started. |
| 5 Land and release | PMM-15532 | Open | Not started. |

Phase 2 in detail. The two branches without a pull request are stacked on the catalogue commit and on `PMM-MCP-GA` from before #6068 was squash-merged, so they need `PMM-MCP-GA` merged in.

| Item | State |
|---|---|
| QAN column catalogue (76 metrics, not the ~90 the ticket says), MongoDB examined and returned counters | #6099, open |
| `pmm_top_queries`: `group_by`, `labels`, `columns`, `order_by` on any column, `offset`, `search`, total rows; decision D10 | `PMM-15529-top-queries-reporting` (`bcfe4b460`), no PR |
| `pmm_get_schema`: 1 to 10 tables in parallel (at most 4 actions in flight), `info_types`; one `PMM_MCP_ACTION_TIMEOUT` bounds a whole call; pmm-agent's own 10 s limit reported as `timeout` | `PMM-15529-schema-multi-table` (`b2bf61618`), no PR |
| Resolve first: `pmm_get_explain` and `pmm_get_schema` from a `queryid` alone | Not started: both still require `service_id`, and `pmm_get_schema` requires `database` and `tables` |
| Table discovery from the EXPLAIN plan | Not started; the ticket's approach doesn't work ([§6.2](#62-pmm_get_schema-from-a-queryid)) |
| `pmm_get_config` beyond numeric variables | Not started; moved out of the epic ([§6.4](#64-pmm_get_config-beyond-numeric-variables)) |

### 3.1 Order from here

Security assumptions and interfaces are settled before more code is built on them. Each step still lands as small PRs onto `PMM-MCP-GA`.

1. **Security model.** A security design review of this spec, centred on ADR-03, 05, 07, 08, 10, 12 and 15 to 18, before the rest of phase 2. The Origin check (ADR-10) lands as the next MCP PR. The implementation review before release stays ([§10](#10-phase-5-release)).
2. **Tool contract.** `tool-contract.md` ([§8](#8-phase-3-output-contract)) written and reviewed, for the phase 2 and phase 2b tools. The phase 2 branches already written land first ([§6.5](#65-landing-order)), and the contract records their inputs.
3. **Rest of phase 2, and phase 2b's metrics tools,** built to the contract ([§6](#6-phase-2-the-rest-of-query-intelligence), [§7.1](#71-metrics), [§7.4](#74-service-health-in-pmm_inventory)); MySQL table discovery is best effort and doesn't block it.
4. **Phase 3 code:** structured output, paging, errors, `pmm_catalog`.
5. **Phase 4:** service-account principals, and Access Roles on the inventory, alert and Advisor APIs ([§9](#9-phase-4-identity-and-access-roles)).
6. **Phase 2b's alerts and Advisors tools,** on those APIs ([§7.2](#72-alerts), [§7.3](#73-advisors)).

Phase 2b is two workstreams under PMM-15790. Metrics (step 3) use APIs that Access Roles already filter. Alerts and Advisors (step 6) depend on phase 4 (step 5). PMM-15790 reports the two separately, so neither shows as blocked by the other.
7. **Phase 5:** client and engine matrix, HA check, security sign-off, release with MCP off ([§10](#10-phase-5-release), [§11](#11-testing-and-verification)).

---

## 4. Architecture

```
MCP client ──HTTPS──▶ nginx  location /mcp
                         │  auth_request: role ≥ Viewer
                         ▼
                      pmm-managed /mcp
                         │  peer must be loopback, else 404 (ADR-10)
                         │  cross-site Origin, 403 (ADR-10, to add)
                         │  PMM_ENABLE_MCP read per request, else 404 (ADR-06)
                         ▼
                      go-sdk Streamable HTTP, Stateless (ADR-04)
                         │  tool handler
                         ▼
                      nginx on loopback (http://127.0.0.1:8080/)
                         │  /v1/… and /graph/api/… with the caller's
                         │  Authorization and Cookie, copied verbatim (ADR-03)
                         │  auth_request again, per backing call: role, LBAC filters
                         ▼
                      pmm-managed, qan-api2, Grafana ──▶ pmm-agent actions (EXPLAIN, SHOW CREATE TABLE)
```

- `/mcp` has the `viewer` rule in `auth_server.go` (`:132`) [V]. nginx `location /mcp` proxies to `managed-json` with buffering off and a 600 s read timeout [V].
- The MCP package never reads ClickHouse, VictoriaMetrics or PostgreSQL and never calls pmm-managed's internal services (`doc.go`) [V].
- The handler never answers 401 itself: that status belongs to `auth_request`. A refused backing call becomes a tool error with code `unauthorized` [V].

**Tools today** (`PMM-MCP-GA`; phase 2 branches change the inputs) [V]. "Live" means a pmm-agent action runs on the monitored database (ADR-05).

| Tool | Returns | Backing API | Kind |
|---|---|---|---|
| `pmm_version` | Server version; confirms the connection and the token | `GET /v1/server/version` | Passive |
| `pmm_inventory` | Services with `service_id`, engine, version, node, address | `GET /v1/inventory/services`, `GET /v1/inventory/nodes`, version metrics | Passive |
| `pmm_top_queries` | Worst queries for a window, ranked, with `queryid` | `POST /v1/qan/metrics:getReport` | Passive |
| `pmm_query_detail` | Fingerprint, engine, schema, tables, key metrics, example | `POST /v1/qan:getMetrics`, `POST /v1/qan/query:getExample` | Passive |
| `pmm_get_explain` | Plan: stored `pg_stat_monitor` plan, live MySQL EXPLAIN, MongoDB explain | QAN plan endpoint, `POST /v1/actions:startServiceAction`, `GET /v1/actions/{id}` | Passive for PostgreSQL; live for MySQL and MongoDB |
| `pmm_get_schema` | Table DDL and indexes | service actions as above | Live |
| `pmm_get_config` | Numeric server variables from collected metrics | inventory, `GET /graph/api/datasources/name/Metrics`, Grafana datasource proxy | Passive |

**Planned tools.** `pmm_inventory` also gains scrape health ([§7.4](#74-service-health-in-pmm_inventory)).

| Tool | Returns | Backing API | Kind | Phase |
|---|---|---|---|---|
| `pmm_catalog` | Reference data: the QAN column catalogue (phase 3) and the metrics catalogue per engine (phase 2b) | None; built into the server | Passive | 3, 2b |
| `pmm_service_health` | 10 to 15 key signals of one service, summarized | Datasource proxy: `/api/v1/query_range` | Passive | 2b |
| `pmm_query_metrics` | Instant or range query results, summarized per series | Datasource proxy: `/api/v1/query`, `/api/v1/query_range` | Passive | 2b |
| `pmm_list_metrics` | Metric names by substring search, label names and values, series | Datasource proxy: `/api/v1/labels`, `/api/v1/label/{name}/values`, `/api/v1/series` | Passive | 2b |
| `pmm_alerts` | Firing alerts with labels, summary and start time | `GET /v1/alerting/alerts` (new, ADR-17) | Passive | 2b |
| `pmm_advisors` | Failed Advisor checks per service | `GET /v1/advisors/failedServices`, `GET /v1/advisors/checks/failed` | Passive | 2b |

**Configuration** [V]:

| Variable | Default | Notes |
|---|---|---|
| `PMM_ENABLE_MCP` | `false` | Also settable through the settings API (`enable_mcp`); read per request. |
| `PMM_MCP_RAW_SQL` | `false` | Environment only; no API setting. |
| `PMM_MCP_ACTION_TIMEOUT` | `15s` | Bounds one `pmm_get_explain` or `pmm_get_schema` call. |
| `PMM_DEV_MCP_LOOPBACK_URL` | `http://127.0.0.1:8080/` | Development only. |

---

## 5. Decisions already taken

### 5.1 Recorded as ADRs

| ADR | Decision | Source | Implemented in |
|---|---|---|---|
| [01](adr/ADR-01-in-server-endpoint.md) | `/mcp` lives in pmm-managed, not in a sidecar or a standalone server | Epic | #5942 |
| [02](adr/ADR-02-base-and-port.md) | #5942 is the base; port #4045's query intelligence, not its chat backend or its unbounded polling | Epic, PMM-15529 | #5942, phase 2 |
| [03](adr/ADR-03-api-only-data-path.md) | Data only through the public API on loopback, with the caller's credentials; MCP authorizes nothing itself | Epic | #5942 |
| [04](adr/ADR-04-stateless-streamable-http.md) | Streamable HTTP, `Stateless`, on the official Go SDK | Epic, implementation notes | #5942 |
| [05](adr/ADR-05-read-only-tools.md) | Every tool read-only; EXPLAIN never executes the statement; live inspection bounded, with a per-caller limit | Epic, review of #4 | #5942; limit in phase 2 |
| [06](adr/ADR-06-off-by-default.md) | Off by default; the setting is read per request and doubles as a kill switch | D5, PMM-15528 | #6068 |
| [07](adr/ADR-07-sql-redaction.md) | `PMM_MCP_RAW_SQL=false`; fail-closed masking; QAN dimension values allowed | D9, D10 | #6068, phase 2 |
| [08](adr/ADR-08-inventory-under-access-roles.md) | Viewer reads the services and nodes inventory, filtered by Access Roles (ADR-16) | D3, PMM-15536, review of #4 | #5942 (rules); filter in phase 4 |
| [09](adr/ADR-09-metrics-via-datasource-proxy.md) | Metrics through Grafana's datasource proxy by uid, with that prefix under LBAC | D7, PMM-15533 | #5942 |
| [10](adr/ADR-10-nginx-only.md) | `/mcp` served only through nginx: SDK localhost protection off, loopback-peer check instead; cross-site `Origin` refused | Implementation notes, review of #4 | #5942, #6068; Origin check next |

`DECISIONS.md` items not carried into ADRs:
- **D1, D2** (where the contributor's branch lived, how commits are named): superseded by `PMM-MCP-GA` in percona/pmm. The branch rules from PMM-15527 move to `plans/00-roadmap.md`.
- **D4** (Access-Role permissions out of scope for #5942): superseded by ADR-12 and ADR-13.
- **D6** (the contributor's demo environment): not carried. Verification uses throwaway VMs from the PMM QA tooling ([§11](#11-testing-and-verification)).
- **D8** (Streamable HTTP response mode): the SDK default (SSE) stays. Revisit only if a client misbehaves behind nginx.

### 5.2 Implementation notes that stay in the spec

- **Lenient decoding of two QAN responses.** qan-api2 encodes non-finite sparkline floats as the strings `"NaN"` and `"Infinity"`, which the generated Swagger client rejects. `qan:getMetrics` and `qan/metrics:getReport` therefore go through a raw POST into types that accept numeric strings [V]. Remove the workaround when PMM-15535 is fixed.
- **Action polling.** 300 ms initial delay, ×1.5 backoff, 2 s maximum, bounded by `PMM_MCP_ACTION_TIMEOUT`. pmm-agent applies its own fixed 10 s limit per action, and runs at most 2 actions at once per database instance and 32 in total (`agent/runner/runner.go:43-44`) [V].

---

## 6. Phase 2: the rest of query intelligence

### 6.1 Resolve first

One internal step turns a `queryid` into the facts every later tool needs: service ID, engine, database or schema, tables and the stored example. It uses `POST /v1/qan/query:getExample` (`QueryExample` carries `service_id`, `service_type`, `schema`, `tables` [V]) plus the metadata `pmm_query_detail` already reads.

A `queryid` alone doesn't name one operation: the same fingerprint can run on several services. A query is identified by `queryid`, service and time window; the engine follows from the service.

MCP is stateless (ADR-04), so the window a model used for one tool doesn't carry over to the next unless the model passes it:
- `pmm_top_queries` and `pmm_query_detail` return a `query_ref` per query: `queryid`, `service_id`, `period_from`, `period_to` (ADR-11).
- `pmm_get_explain` and `pmm_get_schema` accept that `query_ref`, or `queryid` with optional `service_id`, `period_from` and `period_to`. Without a window they use the last hour, as `pmm_top_queries` does, and the result states the window used. A query from yesterday is found by passing its `query_ref`; `queryid` alone is a shortcut for recent queries.
- `service_id` becomes **optional** on `pmm_get_explain` and `pmm_get_schema`.
- Candidates are the services the query was seen on in the window, according to QAN, among the services the caller can see (ADR-08). QAN scopes them by Access Role once PMM-15697 is fixed.
- If `service_id` is given, it must be one of the candidates; otherwise the tool answers `not_found`.
- If it is not given: with exactly one candidate, the tool resolves to it; with several, it answers `invalid_input` and lists them; with none, `not_found`.
- The caller's `service_id` is never used unchecked to fetch a plan.
- The example a MySQL EXPLAIN or a MongoDB explain runs on is the one QAN returns for the resolved service and window, and its `service_id` is checked against that service; an example from another service with the same fingerprint is never used.
- A live MySQL or MongoDB plan is the plan the database would choose now, not the plan it chose during the window; the result says so. A PostgreSQL plan is the one pg_stat_monitor stored.

### 6.2 `pmm_get_schema` from a `queryid`

`pmm_get_schema` takes `queryid` as an alternative to `database` + `tables`.

**Where the table list comes from:**
- **PostgreSQL and MongoDB:** the example's `tables`. pg_stat_monitor sends its relations, pg_stat_statements parses the query with `pg_query_go`, MongoDB sends the collection [V].
- **MySQL:** the QAN agents (perfschema and slowlog) never fill `tables` [V]. So: run `mysql_explain_json`, walk the whole plan tree (`query_block`, `nested_loop`, subqueries, materialized and union nodes) and collect every table entry. Resolve aliases to real names against the explained statement in the action output. A table that can't be resolved is listed as unresolved, never guessed.

MySQL discovery is **best effort** and doesn't block the rest of phase 2. Base tables named in the plan are returned. Derived tables, CTEs and names that need SQL parsing to resolve are listed as unresolved; fixtures widen the coverage over time.

**Why not #4045's approach.** The ticket says to read `real_table_name` "out of the EXPLAIN plan rather than parsing SQL". `real_table_name` is not part of the plan: pmm-agent adds it by parsing the SQL text after the last `FROM `, and returns one table only (`agent/runner/actions/common.go:87`, "due to historical reasons we parsing only one table name") [V]. #4045's `extractTablesFromExplainJSON` reads only that field, so it can't return the tables of a join. It is not ported.

**To verify first [I].** MySQL's version 1 JSON format is believed to report the alias in `table_name`; the version 2 format (`explain_json_format_version=2`, MySQL 8.3 and later) reports `alias` separately. The plan's first task is a fixture test against real EXPLAIN output from the supported MySQL versions, before the walker is written.

### 6.3 `pmm_get_explain` from a `queryid`

With resolve-first, `pmm_get_explain` needs only `queryid`: the engine picks the source (stored plan for PostgreSQL, live action for MySQL and MongoDB), and the database comes from the resolution. `placeholders` and `format` stay as they are.

### 6.4 `pmm_get_config` beyond numeric variables

Moved out of the epic. The exporters publish numeric settings only; the tool's own description already says that string-valued knobs such as `sql_mode` are not in metrics [V]. The Grafana datasource proxy can't return what isn't collected. The pt-summary actions would work, but they are slow, large, and full of host names and paths. PMM-15792 asks the exporters to publish string settings as info metrics; PMM-15529 gets a comment saying why the item left.

### 6.5 Landing order

1. Merge #6099 into `PMM-MCP-GA`.
2. Merge `PMM-MCP-GA` into `PMM-15529-top-queries-reporting`, then open its PR.
3. The same for `PMM-15529-schema-multi-table`.
4. Once `tool-contract.md` covers these tools ([§3.1](#31-order-from-here)), write [§6.1](#61-resolve-first) to [§6.3](#63-pmm_get_explain-from-a-queryid) and the per-caller limit on live inspection (ADR-05) on a new branch from `PMM-MCP-GA`.

### 6.6 Acceptance

PMM-15529's criteria stand, with the `pmm_get_config` item removed:
- `pmm_get_explain` and `pmm_get_schema` work from a `queryid` alone.
- `pmm_top_queries` supports `group_by`, label filters, `columns`, `offset` and `search`, and reports total rows.
- A MySQL query that joins N base tables returns all N definitions; derived tables and CTEs are listed as unresolved.
- No `pmm_get_explain` or `pmm_get_schema` call exceeds `PMM_MCP_ACTION_TIMEOUT` plus slack. Other tools are bounded by the per-request timeout of their backing calls.
- A `service_id` the query was not seen on, or that the caller can't see, returns `not_found`. A query seen on several services returns `invalid_input` listing only services the caller can see.
- A third live-inspection call from the same caller, while two are in flight, returns `rate_limited`; so does a ninth on one replica across callers.
- A `query_ref` returned by `pmm_top_queries` for a window a day old, passed to `pmm_get_explain` and `pmm_get_schema`, resolves the same service and example as `pmm_query_detail` did for that window. The same `queryid` alone, outside the last hour, returns `not_found` and names the window it searched.

---

## 7. Phase 2b: metrics, alerts and Advisors

Ticket: PMM-15790, under PMM-14247. The tools are passive (ADR-05), follow the contract ([§8](#8-phase-3-output-contract)) and are scoped by Access Roles. Two workstreams ([§3.1](#31-order-from-here)): metrics can be built now; alerts and Advisors first need the Access Role work of phase 4 on their APIs ([§9.2](#92-access-roles-on-pmms-service-scoped-apis)).

### 7.1 Metrics

Decision: [ADR-15](adr/ADR-15-metrics-tools.md).

- `pmm_service_health(service_id, range)` returns 10 to 15 key signals of one service, summarized, from a fixed map of queries per engine taken from PMM's dashboards. Each signal carries the time of its last sample, its source metric, and a state: `ok`, `stale` (last sample older than three scrape intervals) or `no_data`. There is no overall healthy or unhealthy verdict. Node signals (CPU, memory, disk) carry node labels only, so a role that filters on service labels hides them and they report `no_data`; the result says that this can mean "hidden" as well as "not sent".
- `pmm_catalog(kind: metrics, engine)` returns the curated catalog: name, meaning, unit, counter or gauge, key labels and a ready query, for 30 to 60 metrics per engine. A CI test checks every entry against exporter `/metrics` fixtures, as the QAN column catalogue is checked against qan-api2 [V].
- `pmm_query_metrics` runs any instant or range query through the datasource proxy (`/api/v1/query`, `/api/v1/query_range`).
- `pmm_list_metrics` searches the metric names on this server. `search` takes a substring such as `mysql` or `mongodb`, escaped before it becomes a `match[]` regex, so `.*` matches literally; `service_id` or `service_name` narrows to one service; label names, label values and the series of a selector help narrow a query (`/api/v1/label/__name__/values` with `match[]`, `/api/v1/labels`, `/api/v1/series`). It always works within a time range. Over the limit, names are grouped by prefix with counts; names in the catalog carry their meaning.
- Access Roles need nothing new: vmproxy injects the caller's filters on all these paths (`vmproxy/proxy/proxy.go:46-50`) [V]. On the label endpoints, VictoriaMetrics honours them unless `-search.ignoreExtraFiltersAtLabelsAPI` is set, and PMM doesn't set it [V]; a test with a restricted role pins this.
- Meaning and type come from the catalog. vmproxy does forward `/api/v1/metadata` (`proxy.go:51`) [V], and VictoriaMetrics 1.137 and later serve it by default [I], but it is empty unless clients send metadata [I] and it can't be filtered by Access Role [I]. This epic doesn't use it (ADR-15).
- **Execution budget** (ADR-15), checked before a query reaches VictoriaMetrics: every selector names a metric (parsed with `metricsql`, a new dependency); the range is capped and the step is set from the point budget; every query carries VictoriaMetrics' `timeout` argument. PMM's own VictoriaMetrics limits (100,000,000 series, 1,500,000,000 samples, 90 s, `supervisord.go:50-55`) [V] are not relied on.
- Every `pmm_query_metrics` response fits one budget ([§8](#8-phase-3-output-contract)): summaries by default, a step chosen to fit, the top N series by max, repeated and internal labels left out of rows, and a narrowing hint built from the caller's expression when a result is cut.
- `Instructions` and the tool description steer toward the built-in signals, the catalog, and aggregated queries.
- All build on `queryMetrics` (`tools_inventory.go:256`), which runs instant queries today [V].
- At most 4 metric queries in flight per caller and 8 per replica across callers; a further call answers `rate_limited`. As for live inspection, "caller" means one token on one replica (ADR-05).

### 7.2 Alerts

Decision: [ADR-17](adr/ADR-17-alerts.md).

- Grafana's alert APIs carry no Access Role filter: `lbacPrefixes` covers only rule tests and evaluation (`auth_server.go:181`) [V].
- Phase 4 adds `GET /v1/alerting/alerts` to pmm-managed, at Viewer. It reads the current alerts from Grafana with the caller's headers, as pmm-managed already does for rule groups (`client.go:732`) [V], and filters them with ADR-16's matcher.
- `pmm_alerts` calls that endpoint. It returns firing alerts, silenced or not (and until when), with name, severity, labels, summary, description, start time and a link, and filters by service, node and severity.
- Which Grafana endpoint the API reads, what a Viewer gets from it, and how folder permissions narrow it are settled on a Feature Build and recorded in ADR-17 before that ADR is accepted.
- An alert belongs to the service its labels name; one without service labels is hidden from restricted callers, whatever their filter's form (ADR-16). Summaries and descriptions are untrusted text (ADR-11) and never used for matching.

### 7.3 Advisors

Decision: [ADR-18](adr/ADR-18-advisors.md).

- `GET /v1/advisors/failedServices` and `GET /v1/advisors/checks/failed` (`checks.go:54`, `:117`) [V] require Editor (`auth_server.go:84-86`) [V] and apply no Access Role filter. Phase 4 adds ADR-16's matcher; the role stays Editor.
- `pmm_advisors` returns failed checks per service, with severity, summary, description and read-more link, and filters by service and severity. A Viewer token gets `unauthorized`.

### 7.4 Service health in `pmm_inventory`

`pmm_inventory` reports each service's scrape health from its `up` series next to its version, read through the datasource proxy like the versions (ADR-09). Scrape targets carry the service's labels (`MergeLabels`, `scrape_configs.go:160`) [V]. It keeps three cases apart: `up` is 1, `up` is 0, and no recent `up` sample, with the time of the last one.

### 7.5 Acceptance

- `pmm_service_health` returns its signals for a MySQL, a PostgreSQL and a MongoDB service, one call each.
- `pmm_catalog(kind: metrics)` returns entries for each engine. The CI test fails when an entry's metric disappears from the exporter fixtures.
- `pmm_query_metrics` answers an instant and a range query. No response exceeds the point and size budget: a result that would is summarized or cut to the top N series, says so, and suggests a narrower query built from the caller's expression.
- `pmm_list_metrics` with `search: mongodb` returns only names that contain `mongodb`; over the limit, it groups them by prefix with counts.
- With an Access Role that allows one service, `pmm_service_health`, `pmm_query_metrics`, `pmm_list_metrics`, `pmm_alerts` and `pmm_advisors` return only that service's series, alerts and results.
- A fifth metric query from the same caller, while four are in flight, returns `rate_limited`; so does a ninth on one replica across callers.
- `{__name__=~".+"}`, a selector without a metric name, and a range over the cap answer `invalid_input` with a hint, and never reach VictoriaMetrics.
- **Load on VictoriaMetrics.** On a server with at least 50 monitored services, five callers each run broad but accepted queries (for example `rate(mysql_global_status_questions[5m])` without aggregation, over 7 days) in a loop for 10 minutes. Record VictoriaMetrics' CPU and memory and the p95 latency of dashboard queries, with and without that load. The security review accepts the numbers or lowers the budgets.
- `pmm_list_metrics` with `search: ".*"` returns only names containing the literal `.*` (none). With a role that allows one service, it returns only that service's names and label values.
- `pmm_service_health` reports `stale` for a service whose exporter stopped, `no_data` for node signals under a service-filtered role, and distinct `up` cases in `pmm_inventory`.
- `pmm_advisors` returns `unauthorized` to a Viewer token and the failed checks to an Editor token.

---

## 8. Phase 3: output contract

Decision: [ADR-11](adr/ADR-11-output-contract.md).

1. **One result value, two renderings.** Each tool gets a Go output type, for example `inventoryResult{Services, Total, Offset, Limit, Truncated}`. The handler builds it once. With a typed `Out`, the SDK infers `outputSchema`, validates the value against it and sends it as `structuredContent`, and keeps the text content the handler sets (`mcp/server.go:387-470` in v1.8.0) [V]. The text, with its "View in PMM" links, is rendered from the same value. For metrics, the text carries the summary table and raw points go only in the structured content (ADR-15).
2. **Redaction on the value.** ADR-07's masking runs on the result value before either rendering, so structured content can't carry what the text withholds. A test runs every tool with `PMM_MCP_RAW_SQL` off and checks both renderings.
3. **Caps and paging.** Every listing tool takes `limit` and `offset` and reports `total`, `offset`, `limit` and `truncated`. The text ends with an explicit marker such as "showing 1–50 of 312; pass offset=50 for more". Starting values, which the token measurement may change:

   | Tool or field | Default | Maximum |
   |---|---|---|
   | `pmm_inventory` services (no cap today, `inventory` in `tools_inventory.go`) | 50 | 200 |
   | `pmm_top_queries` rows | 10 | 100 (unchanged) |
   | `pmm_get_schema` tables | — | 10 (unchanged) |
   | `pmm_get_config` variables | 200 | 1000 |
   | Plan body | — | 64 KiB, with a truncation marker |
   | One table's DDL | — | 32 KiB, with a truncation marker |
   | `pmm_query_metrics` series shown (top N by max) | 20 | 100 |
   | `pmm_query_metrics` points per response | — | 2,000; the step grows to fit, else summaries |
   | `pmm_query_metrics` response size | — | 16 KiB |
   | `pmm_query_metrics` range | 1 h | 7 days |
   | `pmm_query_metrics` query timeout (VictoriaMetrics `timeout` argument) | 30 s | 30 s |
   | Metric queries in flight | 4 per caller | 8 per replica |
   | Live-inspection calls in flight | 2 per caller | 8 per replica |
   | `pmm_list_metrics` names or values | 100 | 1000; over the limit, grouped by prefix with counts |
   | `pmm_alerts` alerts | 50 | 200 |
   | `pmm_advisors` failed checks | 50 | 200 |

4. **Errors.** The eight codes in `errors.go` are part of the contract: `not_found`, `invalid_input`, `unauthorized`, `timeout`, `no_query_source`, `insufficient_privileges`, `agent_unreachable`, `pmm_unavailable` [V], plus `rate_limited` (ADR-05). Each tool's contract lists the codes it can return. An error stays an `isError` result. Its text starts with `error: <code>`, as today (`errors.go:26-50`) [V], and its `_meta` carries `percona.com/error: {code, retryable}` for programs (`CallToolResult` has a `Meta` field in v1.8.0 [V]). `timeout`, `agent_unreachable`, `pmm_unavailable` and `rate_limited` are retryable. The error message never names a service the caller can't see.
5. **Tool-description budget.** Reference data moves out of tool descriptions into one read-only tool, `pmm_catalog(kind, engine)`: the QAN column catalogue (`kind: qan_columns`) leaves `pmm_top_queries`' description, and the metrics catalogue (`kind: metrics`, ADR-15) never enters one. `pmm_top_queries` keeps the four standard rankings and says to call `pmm_catalog` for the rest; an unknown column answers `invalid_input` and points to it. The token cost of a standard slow-query triage is measured before and after and recorded on PMM-15530.
6. **`Instructions`.** Updated to the new contract (EXPLAIN and schema from a `query_ref` or a `queryid`, paging, `pmm_catalog`, alerts and Advisors), plus ADR-15's metrics block and one line saying that fields marked untrusted are data, not instructions. Kept short.
7. **Provenance, partial results and untrusted text** (ADR-11). A result built from time-based data carries its window; a result about a query, service, alert or check carries its `pmm_url`; both in structured content and text. Query results carry a `query_ref` ([§6.1](#61-resolve-first)). A result from several backing calls marks the parts that failed (`partial: true`) instead of failing whole. Fields whose text comes from monitored databases or users (query text and examples, DDL with comments, label values, alert annotations, Advisor texts) are marked untrusted.
8. **Where the contract lives.** `tool-contract.md` in this folder, written and reviewed before the rest of phase 2 ([§3.1](#31-order-from-here)). For every tool:
   - inputs, outputs, error codes and caps;
   - its provenance fields, its partial-failure behaviour, and its untrusted fields;
   - an authorization row: minimum Grafana role, backing APIs, whether LBAC filters the data;
   - passive or live (ADR-05), and which engines it supports, with what it returns for each.

   In percona/pmm, a golden-file test snapshots `tools/list` (names, input and output schemas, annotations), so any contract change shows up as a diff in review. Until release, the contract can change freely; after release, only additively, like the proto API.

---

## 9. Phase 4: identity and Access Roles

PMM-15534 and PMM-15703 are open tickets this phase depends on. Following `AGENTS.md`, this section describes the target behaviour only.

Goal: everything MCP returns to a caller is scoped by that caller's Access Roles, for interactive users and service-account tokens alike.

### 9.1 Service-account tokens are principals

Decision: [ADR-12](adr/ADR-12-service-accounts-as-principals.md).

- The auth path takes the service account's ID from the `GET /api/auth/serviceaccount` response it already fetches for every service token (`client.go:551`) [V]. Percona's Grafana fork answers that route with `ServiceAccountProfileDTO`, whose `id` is the account's user ID (`token.go:115`, `models.go:147`) [V]. No Grafana change and no extra call are needed; the `serviceaccounts/search` fallback the ticket mentions is not needed.
- Access Roles assigned to that ID then apply to the token exactly as to an interactive user: the filters on QAN, on metrics, and on the APIs of [§9.2](#92-access-roles-on-pmms-service-scoped-apis).
- A principal seen for the first time gets the default role, as interactive users do today (`getLBACFilters`, `auth_server.go:482`) [V]. Tokens resolve to user ID 0 today and get no filter (`getAuthUser`, `client.go:291`) [V], so the default role can only narrow what a token sees.
- Roles are assigned to a service account with the existing `POST /v1/accesscontrol/roles:assign` and the account's ID. The docs say how. A role picker on Grafana's service-account page is out of scope.
- `mcp.md` and the access-control docs are updated in the same change to describe role assignment for service accounts.
- **Dropped from the epic:** propagating the caller's identity from `auth_request` to upstreams (`X-User-ID`, sketched in #4045). Every MCP backing call already passes `auth_request`, which resolves the caller, and the MCP layer authorizes nothing (ADR-03). If PMM-15703's fix needs a header, that ticket decides it.

### 9.2 Access Roles on PMM's service-scoped APIs

Decision: [ADR-16](adr/ADR-16-access-roles-on-pmm-apis.md), applied by [ADR-08](adr/ADR-08-inventory-under-access-roles.md), [ADR-17](adr/ADR-17-alerts.md) and [ADR-18](adr/ADR-18-advisors.md).

- Access Roles filter metrics (vmproxy, `extra_filters[]`) and QAN (qan-api2 parses the selectors, `reporter.go:808`) today [V]. Both read `X-Proxy-Filter`, which `auth_request` sets only for paths in `lbacPrefixes` (`auth_server.go:181`) and nginx forwards on every location (`pmm.conf:104`) [V].
- One matcher in pmm-managed applies the same selectors to:
  - `GET /v1/inventory/services` and `/nodes`, at Viewer through the rules from #5942 (`auth_server.go:161-167`) [V];
  - `GET /v1/advisors/failedServices` and `/checks/failed`, at Editor;
  - the new `GET /v1/alerting/alerts`, at Viewer.

  Their paths join `lbacPrefixes`.
- pmm-managed's gRPC gateway has no header matcher today [V], so one is added to pass `X-Proxy-Filter` into gRPC metadata [I].
- **Fail-closed.** vmproxy and qan-api2 treat a missing header as "no restriction", which can't be told apart from a header lost on the way. For pmm-managed's service-scoped paths, `auth_request` always sends the header, with an explicit empty list for an unrestricted caller, and the matcher refuses a request without it (`PermissionDenied`, logged). vmproxy and qan-api2 are unchanged.
- **Missing labels.** A selector matches an item only if the item carries every label the selector names. For positive matchers this is PromQL's behaviour; for `!=`, `!~` and regexes that match the empty string it is stricter, so `{service_name!="production"}` doesn't match an alert without `service_name`. Metrics keep PromQL's behaviour in VictoriaMetrics; the difference shows only for items without a filtered label (ADR-16).
- MCP needs no change for this. It already calls these APIs with the caller's credentials, and every service lookup (`engineOf`, `serviceEngine`) goes through the inventory list (`listServices`, `tools_inventory.go:146`) [V].
- The Viewer inventory rules on `PMM-MCP-GA` don't reach `main` without the matcher.

### 9.3 Access-Role permissions: separate ticket

Decision: [ADR-13](adr/ADR-13-access-role-permissions.md). `mcp:use` as a requirement while Access Control is on, delivered on PMM-15791 after the MCP release. It is governance (who may use MCP), not data scoping, and touches a migration, the proto, the auth path and the role editor (in the Grafana fork today, in the PMM UI after PMM-15744). `inventory:read` is dropped: Access Roles scope the inventory (ADR-08, ADR-16).

### 9.4 Acceptance

- A service-account token resolves to its Grafana user ID.
- An Access Role whose filter matches one service, assigned to a service account or to an interactive Viewer: `pmm_inventory`, `pmm_top_queries`, `pmm_query_metrics` and `pmm_alerts` return only that service's data, and so do the PMM APIs behind them. With an Editor token, `pmm_advisors` does too.
- With that role, a tool given another service's `service_id` returns `not_found`, and no error names another service.
- A node that hosts the visible service is listed; other nodes are listed only when their own labels match.
- An alert without the filtered labels is hidden from that caller, with a positive filter (`{service_name="a"}`) and with a negative one (`{service_name!="production"}`).
- Two services on one node, a role that allows one of them: the other service, its alerts and its Advisor results are hidden; the shared node is listed.
- With the header removed at any hop (gRPC handler, gateway, a call that skips nginx), the inventory, alert and Advisor APIs refuse; a gateway route not covered by `lbacPrefixes` fails the route-coverage unit test.
- With Access Control off, or a role without a filter: every service, as on dashboards.
---

## 10. Phase 5: release

1. **One merge back.** After phases 2, 2b, 3 and 4 are merged into `PMM-MCP-GA` and the security review has passed: merge `main` in, regenerate generated files with `make gen` (never hand-merged), get CI and a Feature Build green, merge `PMM-MCP-GA` into `main`, delete the branch.
2. **Security review, in two passes.** A design review of this spec before the rest of phase 2 ([§3.1](#31-order-from-here)), and an implementation review before the merge back. Scope of both:
   - `/mcp` served only through nginx, and the Origin check (ADR-10);
   - credentials: which header wins, forwarding `Authorization` and `Cookie` over loopback, and that they are never logged (ADR-03, ADR-10);
   - `/mcp` and inventory reads at `viewer`, and Access Roles on the inventory, alert and Advisor APIs, including the fail-closed header and items without a filtered label (ADR-08, ADR-16, ADR-17, ADR-18);
   - model-written metric queries and their limits (ADR-15);
   - service-account tokens under Access Roles (ADR-12);
   - live inspection a Viewer can start, including live EXPLAIN, and its limits (ADR-05);
   - redaction across text and structured content (ADR-07, ADR-11);
   - the sensitivity of EXPLAIN output, DDL, QAN dimension values such as user and client host, and Advisor findings.

   Findings are closed or accepted in writing.
3. **Default state.** Decision: [ADR-14](adr/ADR-14-default-state.md). Off in the release that lands `PMM-MCP-GA`, on new and upgraded servers alike. A later ADR decides the default for the release that drops the Tech Preview label.
4. **Tool-usage telemetry and operator metrics.** In pmm-managed: a counter `mcp_tool_calls_total{tool, code}`, where `code` is `ok` or one of the error codes; a histogram `mcp_tool_duration_seconds{tool}`; and a gauge `mcp_tool_calls_in_flight{tool}`. The existing `pmm-managed` scrape job carries them into VictoriaMetrics (`scrape_configs.go:83`) [V], so operators can see MCP's load next to VictoriaMetrics' own. Telemetry reads only the counter: one new item in `managed/services/telemetry/config.default.yml` reads 24-hour totals per tool and code through the `VM` data source [V], plus whether MCP is enabled. No arguments, queries, service names or users are recorded.
5. **percona/pmm-mcp.** Archive it with a README that points to `/mcp`, and close its two contributor PRs with thanks and the reason (ADR-01).
6. **Docs.** `documentation/docs/api/mcp.md` and `documentation/api/welcome/mcp.md` go live with the release, plus a release-notes entry: what it is, that it is off by default and how to enable it, how Access Roles apply to service-account tokens, and that `pmm_advisors` needs an Editor token.

---

## 11. Testing and verification

Every phase:
- Unit tests next to the code, fixtures under `managed/services/mcp/testdata/`.
- From phase 3, the golden `tools/list` test.
- `api-tests/mcp` against a live server.
- For user-visible changes, a Feature Build from `PMM-MCP-GA` verified on a throwaway VM: the Viewer-token triage from PMM-15528 (`pmm_inventory` → `pmm_top_queries` → `pmm_query_detail` → `pmm_get_explain` → `pmm_get_schema` → `pmm_get_config`), and `POST /mcp` answering 404 when the endpoint is off.

Additionally:
- **Origin check (ADR-10):** a cross-site `Origin` gets 403; a request without `Origin` is served; a non-loopback peer gets 404; a backing call carries the caller's headers unchanged.
- **Phase 2:** MySQL EXPLAIN fixtures from each supported version, and a multi-table join on a live server. The per-caller limit on live inspection.
- **Phase 2b:** the built-in signals and the metrics catalog against exporter fixtures; the response budget on a result with 300 series, with its narrowing hint; summaries; the execution budget's refusals; the load test on VictoriaMetrics ([§7.5](#75-acceptance)); `rate_limited` for metric queries; alerts and Advisors on a server with firing alerts and failed checks.
- **Phase 4:** the Access Role matrix over the inventory, QAN, metrics, alerts and Advisors: Access Control on and off; interactive Viewer, Editor, service token and Admin; a role that allows one service, two roles with different filters, a negative filter, and the default role; two services on one node; alerts with and without service labels. The matcher runs qan-api2's selector cases too. The header-removal and route-coverage tests (ADR-16).
- **Phase 5:**
  - Clients: Claude Code and Cursor against a Feature Build, with a service-account token, on each protocol version the SDK negotiates. For each client, record whether it passes `Instructions` and structured content to the model. Go SDK v1.8.0 supports 2024-11-05 to 2026-07-28 and defaults to 2026-07-28 (`mcp/shared.go:50`) [V].
  - Engines: the triage on MySQL, PostgreSQL and MongoDB, recorded as a tool-by-engine table in `tool-contract.md`.
  - Failure: an agent that is down (`agent_unreachable`), an expired token (`unauthorized`), and pmm-managed restarting mid-call.
  - Agent behaviour: the same triage repeated in a loop, and three investigations in parallel with different tokens, for 10 minutes. Record `rate_limited` answers, the load on the monitored databases and on VictoriaMetrics, and whether every response stayed within its budget.
  - HA: one failover check before the merge back. `Stateless` should make it a non-event; this has not been tested [I].

---

## 12. Corrections to the tickets

| Ticket | Says | Correction |
|---|---|---|
| PMM-14247 | Phases 0 to 5 | Phase 2b added: metrics, alerts and Advisors (ADR-15, ADR-17, ADR-18), PMM-15790. |
| PMM-15527, PMM-15528 | In Progress | Both are merged into `PMM-MCP-GA`; close them or list what is left. |
| PMM-15529 | Read `real_table_name` "out of the EXPLAIN plan" | It is parsed from SQL text, one table only; walk the plan instead ([§6.2](#62-pmm_get_schema-from-a-queryid)). |
| PMM-15529 | ~90-column catalogue | 76 columns, kept in step with qan-api2 by a test [V]. |
| PMM-15529 | Extend `pmm_get_config` past numeric variables through the datasource proxy | Not possible on that path; moved to PMM-15792 ([§6.4](#64-pmm_get_config-beyond-numeric-variables)). |
| PMM-15529 | `pmm_get_explain` and `pmm_get_schema` from a `queryid`, as one requirement | Resolved only to a single service the caller can see; MySQL tables best effort ([§6.1](#61-resolve-first), [§6.2](#62-pmm_get_schema-from-a-queryid)). Built after the contract ([§3.1](#31-order-from-here)). |
| PMM-15530 | Contract spec in percona/pmm `dev/docs/managed/mcp-tool-contract.md`, after phase 2 | `tool-contract.md` in this folder, written before the rest of phase 2. |
| PMM-15530 | Ship the triage playbook in `Instructions` | It exists; phase 3 updates it. |
| PMM-15531 | Identity design in percona/pmm `dev/docs/managed/` | ADR-12, ADR-16 and ADR-08 here. |
| PMM-15531 | Check the fork's response for an ID, else search by name | The response carries `id`; no search needed. |
| PMM-15531 | Propagate caller identity (`X-User-ID`) | Dropped from the epic ([§9.1](#91-service-account-tokens-are-principals)). |
| PMM-15531 | Evaluate the permissions proposal: adopt, defer or drop | Adopted as requirements under Access Control, without a built-in role (ADR-13), on PMM-15791 after the MCP release. Phase 4 instead applies Access Roles to the inventory, alert and Advisor APIs (ADR-16). |
| PMM-15536 | Let Viewers read `GET /v1/inventory/services` and `/nodes` | Adopted, with Access Roles applied to both (ADR-08, ADR-16). |
| PMM-15532 | Decide the GA default on evidence | Off for this release (ADR-14); a later ADR decides when the Tech Preview label goes. |

---

## 13. Risks

- **Phase 4 changes PMM-wide APIs.** Access Roles on the inventory, alert and Advisor APIs change what every restricted caller sees, the PMM UI included (ADR-16).
- **Model-written metric queries** load PMM's own VictoriaMetrics, whose own limits are far too wide to help. The execution budget (metric name required, range cap, step, timeout), the per-caller and per-replica limits, and the load test bound and measure it (ADR-15). Limits are per token and per replica, not per user (ADR-05).
- **Catalog drift.** The built-in signals and the metrics catalog follow exporter metric names; the fixture tests catch renames, at the cost of keeping the fixtures current.
- **Alerts without service labels** are hidden from restricted callers, whatever their filter's form, and Grafana's alert list in the UI stays unscoped (ADR-17). Metrics and this matcher differ for items without a filtered label (ADR-16).
- **Untrusted text reaches the model.** Query text, DDL comments, labels, alert annotations and Advisor texts can carry injected instructions. The contract marks them and `Instructions` warn the model; neither stops a client that acts on them.
- **No per-user MCP switch until ADR-13 ships.** With Access Control on, every Viewer and above can use MCP once an admin enables it; Access Roles still scope what each sees.
- **A long-lived branch in a repository with generated code.** `*.pb.go` and Swagger conflicts are resolved by regenerating, never by hand (roadmap). The phase 2 branches already diverged once.
- **Live inspection under an agent loop.** pmm-agent's limits and the per-caller limit bound the load on a monitored database, but a MongoDB explain still runs its candidate plans (ADR-05).
- **Plan size.** Structured content duplicates the text in each response. The phase 3 measurement must cover both before caps are fixed.
- **MySQL alias resolution** depends on the EXPLAIN JSON format the server emits; versions differ ([§6.2](#62-pmm_get_schema-from-a-queryid)).

## 14. Security-sensitive items

Open tickets this work depends on, referenced by key only: PMM-15339, PMM-15534, PMM-15697, PMM-15702, PMM-15703, PMM-15715. Their details stay in Jira until they are fixed, as `SECURITY.md` and this repository's rules require.
