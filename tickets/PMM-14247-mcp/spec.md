# MCP endpoint in PMM Server: analysis and design (PMM-14247)

- **Date:** 2026-10-22
- **Epic:** [PMM-14247](https://perconadev.atlassian.net/browse/PMM-14247), phases PMM-15527 to PMM-15532 ([§2](#2-sources)).
- **Code base:** percona/pmm branch `PMM-MCP-GA` at `826945906`, and the phase 2 branches listed in [§3](#3-where-the-work-stands). Line numbers refer to those commits; re-check them before you edit.
- **Plans that implement this document:** `plans/00-roadmap.md` and the plans next to it, added once this document is reviewed.

Marks used below:
- **[V]** means verified by reading the code, the ticket or the pull request.
- **[I]** means inferred, or taken from upstream documentation, and not run.

MCP here is the [Model Context Protocol](https://modelcontextprotocol.io).

---

## 1. Summary

**What gets built.** One read-only MCP tool layer inside pmm-managed, served at `https://<pmm-server>/mcp` over MCP Streamable HTTP. Any MCP client (Claude Code, Cursor, a customer's own agent) drives it with an ordinary PMM service-account token. Every tool call goes back out through PMM's public REST API on the nginx loopback with the caller's own credentials, so the MCP layer can never do more than the same token can do with `curl`.

**Where it stands.** Phases 0 and 1 are merged into the integration branch `PMM-MCP-GA`. Phase 2 is partly written on three stacked branches. Phases 3 to 5 have not started ([§3](#3-where-the-work-stands)).

**What this document adds.**
- It records the decisions already implemented as ADR-01 to ADR-10. They were taken in the epic, in pull requests and in `managed/services/mcp/DECISIONS.md`, but none had an architect review, so all start as **Proposed** ([§5](#5-decisions-already-taken)).
- It designs the rest of phase 2 ([§6](#6-phase-2-the-rest-of-query-intelligence)), the output contract (phase 3, ADR-11, [§7](#7-phase-3-output-contract)), identity and permissions (phase 4, ADR-12 and ADR-13, [§8](#8-phase-4-identity-and-permissions)), and the release (phase 5, ADR-14, [§9](#9-phase-5-release)).
- It corrects the phase tickets where they are wrong or outdated ([§11](#11-corrections-to-the-tickets)).

**Where the design material lives.** From now on, here. `DECISIONS.md` and `dev/docs/managed/mcp-access-roles-proposal.md` move from `PMM-MCP-GA` into the ADRs; a later `PMM-MCP-GA` pull request replaces them with a pointer to this folder. The tool contract (phase 3) and the identity design (phase 4), which the tickets place in percona/pmm `dev/docs/managed/`, are written here instead.

---

## 2. Sources

- **Epic** PMM-14247, read in full [V]. It holds the problem statement, the architecture decisions, the phase table and the acceptance criteria.
- **Phase tickets**, read in full [V]: PMM-15527 (phase 0, unblock and cut the branch), PMM-15528 (phase 1, harden), PMM-15529 (phase 2, query intelligence), PMM-15530 (phase 3, output contract), PMM-15531 (phase 4, identity), PMM-15532 (phase 5, land and productize).
- **Related tickets outside the epic** [V]: PMM-15533 (Done), PMM-15534, PMM-15535, PMM-15536. **Children filed later** [V]: PMM-15702, PMM-15703. **Referenced from the code:** PMM-15697, PMM-15715.
- **Pull requests in percona/pmm** [V]:
  - [#5942](https://github.com/percona/pmm/pull/5942): the base implementation, contributed by Sixta Systems. Merged into `PMM-MCP-GA` on 2026-09-21. Its only review is CodeRabbit's.
  - [#6068](https://github.com/percona/pmm/pull/6068): phase 1. Merged into `PMM-MCP-GA` on 2026-10-20, with one human approval.
  - [#6099](https://github.com/percona/pmm/pull/6099): phase 2, QAN column catalogue. Open.
  - [#4045](https://github.com/percona/pmm/pull/4045): Percona's earlier in-server attempt with an AI chat backend. Closed unmerged. Source of the query intelligence ported in phase 2; head `3032de7e1`.
- **percona/pmm-mcp**: a standalone MCP server. Empty apart from a README, with two contributor pull requests open since June and August 2026 (epic).
- **Design files on `PMM-MCP-GA`** [V]: `managed/services/mcp/DECISIONS.md` (D1 to D10 and implementation notes) and `dev/docs/managed/mcp-access-roles-proposal.md`.
- **Go SDK** `github.com/modelcontextprotocol/go-sdk` v1.8.0 (from `go.mod`), source read for the structured-output behaviour [V].
- **percona/grafana**, `pkg/services/serviceaccounts/api/token.go` and `models.go`, read for the service-account response [V].

---

## 3. Where the work stands

As of 2026-10-22 [V]:

| Phase | Ticket | Jira | Code |
|---|---|---|---|
| 0 Unblock, cut `PMM-MCP-GA` | PMM-15527 | In Progress | Branch exists; #5942 merged into it. The CLA, the security-review booking and the contributor replies were not checked. |
| 1 Harden | PMM-15528 | In Progress | #6068 merged into `PMM-MCP-GA`. |
| 2 Query intelligence | PMM-15529 | In Progress | See below. |
| 3 Output contract | PMM-15530 | Open | Not started. An `Instructions` block already exists (`mcp.go:37`). |
| 4 Identity and permissions | PMM-15531 | Open | Not started. |
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

---

## 4. Architecture

```
MCP client ──HTTPS──▶ nginx  location /mcp
                         │  auth_request: role ≥ Viewer
                         ▼
                      pmm-managed /mcp
                         │  peer must be loopback, else 404 (ADR-10)
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

**Tools today** (`PMM-MCP-GA`; phase 2 branches change the inputs) [V]:

| Tool | Returns | Backing API |
|---|---|---|
| `pmm_version` | Server version; confirms the connection and the token | `GET /v1/server/version` |
| `pmm_inventory` | Services with `service_id`, engine, version, node, address | `GET /v1/inventory/services`, `GET /v1/inventory/nodes`, version metrics |
| `pmm_top_queries` | Worst queries for a window, ranked, with `queryid` | `POST /v1/qan/metrics:getReport` |
| `pmm_query_detail` | Fingerprint, engine, schema, tables, key metrics, example | `POST /v1/qan:getMetrics`, `POST /v1/qan/query:getExample` |
| `pmm_get_explain` | Plan: stored `pg_stat_monitor` plan, live MySQL EXPLAIN, MongoDB explain | QAN plan endpoint, `POST /v1/actions:startServiceAction`, `GET /v1/actions/{id}` |
| `pmm_get_schema` | Table DDL and indexes | service actions as above |
| `pmm_get_config` | Numeric server variables from collected metrics | inventory, `GET /graph/api/datasources/name/Metrics`, Grafana datasource proxy |

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
| [05](adr/ADR-05-read-only-tools.md) | Every tool read-only; EXPLAIN never executes the statement | Epic | #5942 |
| [06](adr/ADR-06-off-by-default.md) | Off by default; the setting is read per request and doubles as a kill switch | D5, PMM-15528 | #6068 |
| [07](adr/ADR-07-sql-redaction.md) | `PMM_MCP_RAW_SQL=false`; fail-closed masking; QAN dimension values allowed | D9, D10 | #6068, phase 2 |
| [08](adr/ADR-08-viewer-reads-inventory.md) | Viewer can read the services and nodes inventory | D3, PMM-15536 | #5942 |
| [09](adr/ADR-09-metrics-via-datasource-proxy.md) | Metrics through Grafana's datasource proxy by uid, with that prefix under LBAC | D7, PMM-15533 | #5942 |
| [10](adr/ADR-10-nginx-only.md) | `/mcp` served only through nginx: SDK localhost protection off, loopback-peer check instead | Implementation notes | #5942, #6068 |

`DECISIONS.md` items not carried into ADRs:
- **D1, D2** (where the contributor's branch lived, how commits are named): superseded by `PMM-MCP-GA` in percona/pmm. The branch rules from PMM-15527 move to `plans/00-roadmap.md`.
- **D4** (Access-Role permissions out of scope for #5942): superseded by ADR-12 and ADR-13.
- **D6** (the contributor's demo environment): not carried. Verification uses throwaway VMs from the PMM QA tooling ([§10](#10-testing-and-verification)).
- **D8** (Streamable HTTP response mode): the SDK default (SSE) stays. Revisit only if a client misbehaves behind nginx.

### 5.2 Implementation notes that stay in the spec

- **Lenient decoding of two QAN responses.** qan-api2 encodes non-finite sparkline floats as the strings `"NaN"` and `"Infinity"`, which the generated Swagger client rejects. `qan:getMetrics` and `qan/metrics:getReport` therefore go through a raw POST into types that accept numeric strings [V]. Remove the workaround when PMM-15535 is fixed.
- **Action polling.** 300 ms initial delay, ×1.5 backoff, 2 s maximum, bounded by `PMM_MCP_ACTION_TIMEOUT`. pmm-agent applies its own fixed 10 s limit per action [V].
- **Prefix rules widen to single objects.** `resolveRule` walks prefixes, so the inventory read rules (ADR-08) also allow `GET /v1/inventory/services/{id}` and `GET /v1/inventory/nodes/{id}`. The fields are the same as in the lists [V].

---

## 6. Phase 2: the rest of query intelligence

### 6.1 Resolve first

One internal step turns a `queryid` into the facts every later tool needs: service ID, engine, database or schema, tables and the stored example. It uses `POST /v1/qan/query:getExample` (`QueryExample` carries `service_id`, `service_type`, `schema`, `tables` [V]) plus the metadata `pmm_query_detail` already reads.

- `service_id` becomes **optional** on `pmm_get_explain` and `pmm_get_schema`.
- If it is given, it must be one of the services the query was seen on in the window; otherwise the tool answers `not_found`.
- If it is not given and the query ran on more than one service, the tool answers `invalid_input` and lists the candidates.
- The caller's `service_id` is never used unchecked to fetch a plan.

### 6.2 `pmm_get_schema` from a `queryid`

`pmm_get_schema` takes `queryid` as an alternative to `database` + `tables`.

**Where the table list comes from:**
- **PostgreSQL and MongoDB:** the example's `tables`. pg_stat_monitor sends its relations, pg_stat_statements parses the query with `pg_query_go`, MongoDB sends the collection [V].
- **MySQL:** the QAN agents (perfschema and slowlog) never fill `tables` [V]. So: run `mysql_explain_json`, walk the whole plan tree (`query_block`, `nested_loop`, subqueries, materialized and union nodes) and collect every table entry. Resolve aliases to real names against the explained statement in the action output. A table that can't be resolved is listed as unresolved, never guessed.

**Why not #4045's approach.** The ticket says to read `real_table_name` "out of the EXPLAIN plan rather than parsing SQL". `real_table_name` is not part of the plan: pmm-agent adds it by parsing the SQL text after the last `FROM `, and returns one table only (`agent/runner/actions/common.go:87`, "due to historical reasons we parsing only one table name") [V]. #4045's `extractTablesFromExplainJSON` reads only that field, so it can't return the tables of a join. It is not ported.

**To verify first [I].** MySQL's version 1 JSON format is believed to report the alias in `table_name`; the version 2 format (`explain_json_format_version=2`, MySQL 8.3 and later) reports `alias` separately. The plan's first task is a fixture test against real EXPLAIN output from the supported MySQL versions, before the walker is written.

### 6.3 `pmm_get_explain` from a `queryid`

With resolve-first, `pmm_get_explain` needs only `queryid`: the engine picks the source (stored plan for PostgreSQL, live action for MySQL and MongoDB), and the database comes from the resolution. `placeholders` and `format` stay as they are.

### 6.4 `pmm_get_config` beyond numeric variables

Moved out of the epic. The exporters publish numeric settings only; the tool's own description already says that string-valued knobs such as `sql_mode` are not in metrics [V]. The Grafana datasource proxy can't return what isn't collected. The pt-summary actions would work, but they are slow, large, and full of host names and paths. A follow-up ticket asks the exporters to publish string settings as info metrics; PMM-15529 gets a comment saying why the item left.

### 6.5 Landing order

1. Merge #6099 into `PMM-MCP-GA`.
2. Merge `PMM-MCP-GA` into `PMM-15529-top-queries-reporting`, then open its PR.
3. The same for `PMM-15529-schema-multi-table`.
4. Write [§6.1](#61-resolve-first) to [§6.3](#63-pmm_get_explain-from-a-queryid) on a new branch from `PMM-MCP-GA`.

### 6.6 Acceptance

PMM-15529's criteria stand, with the `pmm_get_config` item removed:
- `pmm_get_explain` and `pmm_get_schema` work from a `queryid` alone.
- `pmm_top_queries` supports `group_by`, label filters, `columns`, `offset` and `search`, and reports total rows.
- A MySQL query that joins N tables returns all N definitions.
- No tool call exceeds `PMM_MCP_ACTION_TIMEOUT` plus slack.
- A `service_id` the query was not seen on, or that the caller can't see, returns `not_found`.

---

## 7. Phase 3: output contract

Decision: [ADR-11](adr/ADR-11-output-contract.md).

1. **One result value, two renderings.** Each tool gets a Go output type, for example `inventoryResult{Services, Total, Offset, Limit, Truncated}`. The handler builds it once. With a typed `Out`, the SDK infers `outputSchema`, validates the value against it and sends it as `structuredContent`, and keeps the text content the handler sets (`mcp/server.go:387-470` in v1.8.0) [V]. The text, with its "View in PMM" links, is rendered from the same value.
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

4. **Errors.** The eight codes in `errors.go` are part of the contract: `not_found`, `invalid_input`, `unauthorized`, `timeout`, `no_query_source`, `insufficient_privileges`, `agent_unreachable`, `pmm_unavailable` [V]. Each tool's contract lists the codes it can return. Errors stay `isError` results without structured content.
5. **Tool-description budget.** The QAN column catalogue moves out of `pmm_top_queries`' description into a new read-only tool, `pmm_qan_columns`. `pmm_top_queries` keeps the four standard rankings and says to call `pmm_qan_columns` for the rest; an unknown column answers `invalid_input` and points to it. The token cost of a standard slow-query triage is measured before and after and recorded on PMM-15530.
6. **`Instructions`.** Updated to the new contract (EXPLAIN and schema from a `queryid` alone, paging, `pmm_qan_columns`) and kept short.
7. **Where the contract lives.** `tool-contract.md` in this folder: every tool's input, output, error codes and caps, written and reviewed before the code. In percona/pmm, a golden-file test snapshots `tools/list` (names, input and output schemas, annotations), so any contract change shows up as a diff in review. Until release, the contract can change freely; after release, only additively, like the proto API.

---

## 8. Phase 4: identity and permissions

PMM-15534 and PMM-15703 are open tickets this phase depends on. Following `AGENTS.md`, this section describes the target behaviour only.

### 8.1 Service-account tokens are principals

Decision: [ADR-12](adr/ADR-12-service-accounts-as-principals.md).

- The auth path takes the service account's ID from the `GET /api/auth/serviceaccount` response it already fetches for every service token (`client.go:551`) [V]. Percona's Grafana fork answers that route with `ServiceAccountProfileDTO`, whose `id` is the account's user ID (`token.go:115`, `models.go:147`) [V]. No Grafana change and no extra call are needed; the `serviceaccounts/search` fallback the ticket mentions is not needed.
- Access Roles assigned to that ID then apply to the token exactly as to an interactive user: LBAC filters on `/v1/qan/` and on the datasource proxy, and the permissions of [§8.2](#82-access-role-permissions).
- A principal seen for the first time gets the default role, as interactive users do today (`getLBACFilters`, `auth_server.go:482`) [V].
- Roles are assigned to a service account with the existing `POST /v1/accesscontrol/roles:assign` and the account's ID. The docs say how. A role picker on Grafana's service-account page is out of scope.
- `mcp.md` and the access-control docs are updated in the same change to describe role assignment for service accounts.
- **Dropped from the epic:** propagating the caller's identity from `auth_request` to upstreams (`X-User-ID`, sketched in #4045). Every MCP backing call already passes `auth_request`, which resolves the caller, and the MCP layer authorizes nothing (ADR-03). If PMM-15703's fix needs a header, that ticket decides it.

### 8.2 Access-Role permissions

Decision: [ADR-13](adr/ADR-13-access-role-permissions.md). Adopted, as **requirements while Access Control is on**.

- **Vocabulary:** `mcp:use` and `inventory:read`.
- **Model:** a forward-only migration adds `permissions text[]` to `roles`; the reform model and helpers follow. Additive `repeated string permissions` on the role messages in `api/accesscontrol/v1beta1/accesscontrol.proto` (`CreateRoleRequest`, `UpdateRoleRequest`, `GetRoleResponse`, `ListRolesResponse.RoleData`) [V], then `make gen`.
- **Enforcement:** a `permissionRules` map in `auth_server.go`: `/mcp` → `mcp:use`; `GET /v1/inventory/services` and `GET /v1/inventory/nodes` → `inventory:read`. In `authenticate`, after the Grafana-role check passes: if Access Control is on, the caller is not Admin, and the path matches a rule, the caller's roles must carry the permission, or the request gets 403. A user's permissions are the union over their roles.
- **Access Control off:** no effect; ADR-08 applies as is.
- **No built-in role.** A role with an empty filter gives full visibility whatever the user's other roles say (`auth_server.go:519`) [V], so a built-in "MCP User" role without a filter would widen a restricted user's access. Admins add the permissions to the roles users already hold, or to the default role for everyone. Permissions never change what a user can see.
- **UI:** a Permissions checkbox group in the Access Roles editor, which lives in the Grafana fork (`public/app/percona/shared/services/roles/`) [V].
- **Effect on MCP:** none in the MCP code. Every tool call is re-authorized by `auth_request` on its backing path, so a caller without `inventory:read` gets `unauthorized` from `pmm_inventory`, and a caller without `mcp:use` never reaches `/mcp`.

### 8.3 Acceptance

- A service-account token resolves to its Grafana user ID.
- An Access Role whose filter matches one service, assigned to a service account: `pmm_inventory` and `pmm_top_queries` with its token return only that service, through both `/v1/qan/` and the datasource proxy.
- With Access Control on: a Viewer without `mcp:use` gets 403 on `/mcp`; with it, the full triage works; Admin always works. With Access Control off: unchanged.

---

## 9. Phase 5: release

1. **One merge back.** After phases 2 to 4 are merged into `PMM-MCP-GA` and the security review has passed: merge `main` in, regenerate generated files with `make gen` (never hand-merged), get CI and a Feature Build green, merge `PMM-MCP-GA` into `main`, delete the branch.
2. **Formal security review.** Scope:
   - `/mcp` served only through nginx (ADR-10);
   - the widened auth rules: `/mcp` and inventory reads at `viewer` (ADR-08);
   - the permission requirements (ADR-13);
   - read-only agent actions a Viewer can start, including live EXPLAIN;
   - redaction across text and structured content (ADR-07, ADR-11);
   - the sensitivity of EXPLAIN output and DDL;
   - forwarding `Authorization` and `Cookie` over loopback, and that they are never logged.

   Findings are closed or accepted in writing.
3. **Default state.** Decision: [ADR-14](adr/ADR-14-default-state.md). Phase 5 decides the default for the release that lands `PMM-MCP-GA`, and turns it on only when its conditions hold. A new default applies to new installations only.
4. **Tool-usage telemetry.** A counter `mcp_tool_calls_total{tool, code}` in pmm-managed, where `code` is `ok` or one of the error codes. The existing `pmm-managed` scrape job carries it into VictoriaMetrics (`scrape_configs.go:83`) [V]. One new item in `managed/services/telemetry/config.default.yml` reads 24-hour totals per tool and code through the `VM` data source [V], plus whether MCP is enabled. No arguments, queries, service names or users are recorded.
5. **percona/pmm-mcp.** Archive it with a README that points to `/mcp`, and close its two contributor PRs with thanks and the reason (ADR-01).
6. **Docs.** `documentation/docs/api/mcp.md` and `documentation/api/welcome/mcp.md` go live with the release, plus a release-notes entry: what it is, its default state, how to enable it, which permissions Access Control needs.

---

## 10. Testing and verification

Every phase:
- Unit tests next to the code, fixtures under `managed/services/mcp/testdata/`.
- From phase 3, the golden `tools/list` test.
- `api-tests/mcp` against a live server.
- For user-visible changes, a Feature Build from `PMM-MCP-GA` verified on a throwaway VM: the Viewer-token triage from PMM-15528 (`pmm_inventory` → `pmm_top_queries` → `pmm_query_detail` → `pmm_get_explain` → `pmm_get_schema` → `pmm_get_config`), and `POST /mcp` answering 404 when the endpoint is off.

Additionally:
- **Phase 2:** MySQL EXPLAIN fixtures from each supported version, and a multi-table join on a live server.
- **Phase 4:** the Access Control matrix: on and off, with and without each permission, interactive user and service token, Admin.
- **Phase 5:** one failover check on an HA cluster before the merge back. `Stateless` should make it a non-event; this has not been tested [I].

---

## 11. Corrections to the tickets

| Ticket | Says | Correction |
|---|---|---|
| PMM-15527, PMM-15528 | In Progress | Both are merged into `PMM-MCP-GA`; close them or list what is left. |
| PMM-15529 | Read `real_table_name` "out of the EXPLAIN plan" | It is parsed from SQL text, one table only; walk the plan instead ([§6.2](#62-pmm_get_schema-from-a-queryid)). |
| PMM-15529 | ~90-column catalogue | 76 columns, kept in step with qan-api2 by a test [V]. |
| PMM-15529 | Extend `pmm_get_config` past numeric variables through the datasource proxy | Not possible on that path; moved to a follow-up ([§6.4](#64-pmm_get_config-beyond-numeric-variables)). |
| PMM-15530 | Contract spec in percona/pmm `dev/docs/managed/mcp-tool-contract.md` | `tool-contract.md` in this folder. |
| PMM-15530 | Ship the triage playbook in `Instructions` | It exists; phase 3 updates it. |
| PMM-15531 | Identity design in percona/pmm `dev/docs/managed/` | ADR-12 and ADR-13 here. |
| PMM-15531 | Check the fork's response for an ID, else search by name | The response carries `id`; no search needed. |
| PMM-15531 | Propagate caller identity (`X-User-ID`) | Dropped from the epic ([§8.1](#81-service-account-tokens-are-principals)). |
| PMM-15531 | Evaluate the permissions proposal: adopt, defer or drop | Adopted as requirements under Access Control, without a built-in role (ADR-13). Phase 4 grows to include a migration, proto, auth and Grafana UI changes. |
| PMM-15532 | Decide the GA default on evidence | ADR-14 sets the conditions, and a new default applies to new installations only. |

---

## 12. Risks

- **Phase 4 is now cross-repository.** Permissions touch a migration, the proto, the auth path and the Grafana fork's Access Roles editor. The fork needs a matching release.
- **A long-lived branch in a repository with generated code.** `*.pb.go` and Swagger conflicts are resolved by regenerating, never by hand (roadmap). The phase 2 branches already diverged once.
- **Enabled by default exposes an LLM-facing surface on every new server.** ADR-14's conditions, the security review and the permission requirement under Access Control are the guard rails.
- **Plan size.** Structured content duplicates the text in each response. The phase 3 measurement must cover both before caps are fixed.
- **MySQL alias resolution** depends on the EXPLAIN JSON format the server emits; versions differ ([§6.2](#62-pmm_get_schema-from-a-queryid)).

## 13. Security-sensitive items

Open tickets this work depends on, referenced by key only: PMM-15534, PMM-15697, PMM-15702, PMM-15703, PMM-15715. Their details stay in Jira until they are fixed, as `SECURITY.md` and this repository's rules require.
