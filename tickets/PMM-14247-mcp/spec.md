# MCP endpoint in PMM Server: analysis and design (PMM-14247)

- **Date:** 2026-10-22, revised 2026-10-24, 2026-10-26, 2026-10-30, 2026-11-02 and 2026-11-04 after reviews of [pmm-specs#4](https://github.com/Percona-Lab/pmm-specs/pull/4), and 2026-11-06 after the security design review ([§3.1](#31-order-from-here)).
- **Epic:** [PMM-14247](https://perconadev.atlassian.net/browse/PMM-14247), phases PMM-15527 to PMM-15532 ([§2](#2-sources)).
- **Code base:** percona/pmm branch `PMM-MCP-GA` at `826945906`, and the phase 2 branches listed in [§3](#3-where-the-work-stands). Line numbers refer to those commits; re-check them before you edit.
- **Plans that implement this document:** [`plans/00-roadmap.md`](plans/00-roadmap.md) and the plans next to it.

Marks used below:
- **[V]** means verified by reading the code, the ticket or the pull request.
- **[I]** means inferred, or taken from upstream documentation, and not run.

MCP here is the [Model Context Protocol](https://modelcontextprotocol.io).

---

## 1. Summary

**What gets built.** One read-only MCP tool layer inside pmm-managed, served at `https://<pmm-server>/mcp` over MCP Streamable HTTP. The tools cover query triage (QAN, EXPLAIN, schema, configuration), metrics and firing alerts. Any MCP client (Claude Code, Cursor, a customer's own agent) drives it with an ordinary PMM service-account token. Every tool call goes back out through PMM's public REST API on the nginx loopback with the caller's own credentials, so the MCP layer can never do more than the same token can do with `curl`.

**Where it stands.** Phases 0 and 1 are merged into the integration branch `PMM-MCP-GA`. Phase 2 is partly written in three stacked pull requests. Phases 2b to 5 have not started ([§3](#3-where-the-work-stands)).

**What this document adds.**
- It records the decisions already implemented as ADR-01 to ADR-10. They were taken in the epic, in pull requests and in `managed/services/mcp/DECISIONS.md`, but none had an architect review, so all start as **Proposed** ([§5](#5-decisions-already-taken)).
- It designs the remaining work:
  - the rest of phase 2: [§6](#6-phase-2-the-rest-of-query-intelligence);
  - phase 2b, metrics and alerts, with Advisor results left out of the Tech Preview: ADR-15, ADR-17, ADR-18, [§7](#7-phase-2b-metrics-alerts-and-advisors);
  - phase 3, the output contract: ADR-11, [§8](#8-phase-3-output-contract);
  - phase 4, the caller's service list and service-account tokens: ADR-08, ADR-12, [§9](#9-phase-4-identity-and-access-roles);
  - phase 5, the release: ADR-14, [§10](#10-phase-5-release).
- Access-Role permissions (ADR-13) move to PMM-15791, after the MCP release. Access Roles on PMM's own service-scoped APIs (ADR-16) are deferred to a PMM ticket, not yet filed, whose work lands on `main`.
- It corrects the phase tickets where they are wrong or outdated ([§12](#12-corrections-to-the-tickets)).

**Where the design material lives.** This folder is the design record. `DECISIONS.md` and `dev/docs/managed/mcp-access-roles-proposal.md` move from `PMM-MCP-GA` into the ADRs; a later `PMM-MCP-GA` pull request replaces them with a pointer to this folder. The tool contract (phase 3) and the identity design (phase 4), which the tickets place in percona/pmm `dev/docs/managed/`, are written here instead.

### 1.1 Problem

PMM users want to ask an AI client about their databases: which queries are slow, why, what the server's metrics and alerts say. Earlier attempts either bundled an AI chat backend into PMM or stayed an empty standalone project ([ADR-01](adr/ADR-01-in-server-endpoint.md)); reading PMM's stores with one shared credential bypasses per-caller authorization ([ADR-03](adr/ADR-03-api-only-data-path.md)). None reached `main`.

### 1.2 Goals

- An AI client reads PMM data through MCP with the caller's own PMM credentials, and never gets more than those credentials give through PMM's API.
- Metrics and QAN data are filtered by the caller's Access Roles, for interactive users and service-account tokens alike; MCP narrows its other results to the services those roles allow (not a security boundary, ADR-03).
- A slow-query triage (inventory, top queries, detail, EXPLAIN, schema, configuration) works on MySQL, PostgreSQL and MongoDB, with bounded responses and bounded load on the monitored databases and on VictoriaMetrics.
- Metrics and firing alerts are readable the same way.
- The release ships off by default, as a Tech Preview; tool-usage telemetry informs when the label drops ([ADR-14](adr/ADR-14-default-state.md)).

### 1.3 Non-goals

- Write tools of any kind ([ADR-05](adr/ADR-05-read-only-tools.md)).
- Access Roles on pmm-managed's own APIs and on Grafana's alerts ([ADR-16](adr/ADR-16-access-roles-on-pmm-apis.md), deferred).
- Alert history ([ADR-17](adr/ADR-17-alerts.md)).
- Advisor results ([ADR-18](adr/ADR-18-advisors.md)).
- String-valued configuration ([§6.4](#64-pmm_get_config-beyond-numeric-variables)).
- A per-user MCP switch before the release ([ADR-13](adr/ADR-13-access-role-permissions.md)).
- Propagating the caller's identity to upstreams, a machine principal, and a role picker for service accounts ([ADR-12](adr/ADR-12-service-accounts-as-principals.md)).
- Live metric metadata ([ADR-15](adr/ADR-15-metrics-tools.md)) and a limiter shared across replicas ([ADR-05](adr/ADR-05-read-only-tools.md)).

### 1.4 Terms

- **QAN:** PMM's Query Analytics, served by qan-api2.
- **Access Roles:** PMM roles that carry a label filter, a series selector such as `{environment="prod"}`; this is PMM's label-based access control (LBAC). With Access Control on, a user or service account sees only the metrics and QAN data its roles' filters match; several roles combine with OR, and a role without a filter gives full access. Admins assign them with `POST /v1/accesscontrol/roles:assign`; a principal seen for the first time gets the default role. See percona/pmm [`dev/docs/managed/access-control.md`](https://github.com/percona/pmm/blob/main/dev/docs/managed/access-control.md).
- **Grafana role:** Viewer, Editor or Admin, which PMM's auth server checks per path.
- **The caller's service list:** the services and nodes in the `up` series the caller can read (ADR-08).
- **Filtered** means the backing API applies the caller's Access Roles; **narrowed** means MCP drops results outside the caller's service list. Narrowing is not a security boundary (ADR-03).
- **Live inspection:** a tool call that runs a pmm-agent action on the monitored database (MySQL and MongoDB EXPLAIN, DDL, indexes); **passive** tools read data PMM already stores (ADR-05).
- **AI client:** the MCP client and the model behind it; **pmm-agent** is PMM's agent on the monitored host.
- **Feature Build:** PMM Server and client images built from a branch for live checks; Percona engineers get one through a draft PR in Percona-Lab/pmm-submodules, and outside contributors build and run PMM locally (percona/pmm `dev/docs/process/running-and-verifying-locally.md`).
- **Reference triage:** `pmm_inventory` → `pmm_top_queries` → `pmm_query_detail` → `pmm_get_explain` → `pmm_get_schema` → `pmm_get_config`, with a Viewer token.
- **Smallest supported server:** the minimum in PMM's hardware requirements (`documentation/docs/install-pmm/plan-pmm-installation/hardware_and_system.md`).

---

## 2. Sources

- **Epic** PMM-14247, read in full [V]. Its problem statement and goals are summarized in [§1.1](#11-problem) and [§1.2](#12-goals).
- **Phase tickets**, read in full [V]: PMM-15527 (phase 0, unblock and cut the branch), PMM-15528 (phase 1, harden), PMM-15529 (phase 2, query intelligence), PMM-15530 (phase 3, output contract), PMM-15531 (phase 4, identity), PMM-15532 (phase 5, land and productize).
- **Related tickets outside the epic** [V]: PMM-15533 (Done), PMM-15534, PMM-15535, PMM-15536. **Children filed later** [V]: PMM-15702, PMM-15703. **Filed with this spec:** PMM-15790 (phase 2b), PMM-15791 (ADR-13), PMM-15792 (§6.4). **Referenced from the code:** PMM-15697, PMM-15715.
- **Pull requests in percona/pmm** [V]:
  - [#5942](https://github.com/percona/pmm/pull/5942): the base implementation, contributed by Sixta Systems. Merged into `PMM-MCP-GA` on 2026-09-21 after an automated review (CodeRabbit); this is why ADR-01 to ADR-10 start as Proposed.
  - [#6068](https://github.com/percona/pmm/pull/6068): phase 1. Merged into `PMM-MCP-GA` on 2026-10-20, with one human approval.
  - [#6099](https://github.com/percona/pmm/pull/6099), [#6100](https://github.com/percona/pmm/pull/6100), [#6101](https://github.com/percona/pmm/pull/6101): phase 2, stacked in that order. Open.
  - [#4045](https://github.com/percona/pmm/pull/4045): Percona's earlier in-server attempt with an AI chat backend. Closed unmerged. Source of the query intelligence ported in phase 2; head `3032de7e1`.
- **percona/pmm-mcp**: a standalone MCP server. Empty apart from a README, with two contributor pull requests open since June and August 2026 (epic).
- **Design files on `PMM-MCP-GA`** [V]: `managed/services/mcp/DECISIONS.md` (D1 to D10 and implementation notes) and `dev/docs/managed/mcp-access-roles-proposal.md`.
- **Go SDK** `github.com/modelcontextprotocol/go-sdk` v1.8.0 (from `go.mod`), source read for the structured-output behaviour [V].
- **How Access Roles are applied today** [V]: vmproxy (`vmproxy/proxy/proxy.go`), qan-api2 (`qan-api2/models/reporter.go`), and in pmm-managed the auth server, the Advisors API (`managed/services/management/checks.go`) and the Grafana client.
- **percona/grafana**, `pkg/services/serviceaccounts/api/token.go` and `models.go`, read for the service-account response [V].

---

## 3. Where the work stands

As of 2026-11-02 [V]:

| Phase | Ticket | Jira | Code |
|---|---|---|---|
| 0 Unblock, cut `PMM-MCP-GA` | PMM-15527 | In Progress | Branch exists; #5942 merged into it. The CLA, the security-review booking and the contributor replies were not checked. |
| 1 Harden | PMM-15528 | In Progress | #6068 merged into `PMM-MCP-GA`. |
| 2 Query intelligence | PMM-15529 | In Progress | See below. |
| 2b Metrics, alerts and Advisors | PMM-15790 | Open | Not started. |
| 3 Output contract | PMM-15530 | Open | Not started. An `Instructions` block already exists (`mcp.go:37`). |
| 4 Service list and identity | PMM-15531 | Open | Not started. PMM-15534 (ADR-12) lands on `main`. |
| 5 Land and release | PMM-15532 | Open | Not started. |

Phase 2 in detail. #6100 and #6101 are stacked on #6099 and on `PMM-MCP-GA` from before #6068 was squash-merged, so merging them would replay #6068's commits; [plan 01](plans/01-land-phase-2.md) rebuilds them by cherry-pick.

| Item | State |
|---|---|
| QAN column catalog (76 columns, not the ~90 the ticket says), MongoDB examined and returned counters | #6099, open |
| `pmm_top_queries`: `group_by`, `labels`, `columns`, `order_by` on any column, `offset`, `search`, total rows; decision D10 | #6100 (`bcfe4b460`), open |
| `pmm_get_schema`: 1 to 10 tables in parallel (at most 4 actions in flight), `info_types`; one `PMM_MCP_ACTION_TIMEOUT` bounds a whole call; pmm-agent's own 10 s limit reported as `timeout` | #6101 (`b2bf61618`), open |
| Resolve first: `pmm_get_explain` and `pmm_get_schema` from a `queryid` alone | Not started: both still require `service_id`, and `pmm_get_schema` requires `database` and `tables` |
| Table discovery from the EXPLAIN plan | Not started; the ticket's approach finds one table per query ([§6.2](#62-pmm_get_schema-from-a-queryid)) |
| `pmm_get_config` beyond numeric variables | Not started; moved out of the epic ([§6.4](#64-pmm_get_config-beyond-numeric-variables)) |

### 3.1 Order from here

The order, the dependencies and the branch rules are in [plans/00-roadmap.md](plans/00-roadmap.md); each plan lands as its own PR onto `PMM-MCP-GA`. In short:

1. Land the phase 2 pull requests ([plan 01](plans/01-land-phase-2.md)).
2. Harden `/mcp`: the Origin check, the refusal of anonymous callers, and the caps and cancellation of live inspection ([plan 02](plans/02-origin-and-limits.md)).
3. The output contract ([plan 03](plans/03-output-contract.md), [§8](#8-phase-3-output-contract)); its first task writes `tool-contract.md`.
4. A security design review of this folder and `tool-contract.md`, before plans 04 to 07. It took place on 2026-11-06, against pmm-specs `main` at `80c9b8b` and percona/pmm `PMM-MCP-GA` at `83baa4430`, by three independent reviewers. Its findings are recorded in Jira (Developers-only); those about code PMM already ships are reported privately, as `SECURITY.md` requires. The design changes it asked for are in this folder. Plans 04 to 07 may start.
5. Resolve first ([plan 04](plans/04-resolve-first.md), [§6](#6-phase-2-the-rest-of-query-intelligence)).
6. Metrics ([plan 05](plans/05-metrics.md), [§7.1](#71-metrics)).
7. The caller's service list ([plan 06](plans/06-access-roles.md), [§9](#9-phase-4-identity-and-access-roles)); PMM-15534 lands on `main` meanwhile.
8. Alerts ([plan 07](plans/07-alerts-and-advisors.md), [§7.2](#72-alerts)); Advisor results stay out of the Tech Preview ([§7.3](#73-advisors)).
9. The release ([plan 08](plans/08-release.md), [§10](#10-phase-5-release)).

---

## 4. Architecture

```text
MCP client ──HTTPS──▶ nginx  location /mcp
                         │  auth_request: role ≥ Viewer; an anonymous caller gets 403 (ADR-10, plan 02)
                         ▼
                      pmm-managed /mcp
                         │  peer must be loopback, else 404 (ADR-10)
                         │  PMM_ENABLE_MCP read per request, else 404 (ADR-06)
                         │  cross-site Origin, 403 (ADR-10, plan 02)
                         ▼
                      go-sdk Streamable HTTP, Stateless (ADR-04)
                         │  tool handler: per-caller and per-replica caps (ADR-05, ADR-15);
                         │  results narrowed to the caller's service list (ADR-03, ADR-08)
                         ▼
                      nginx on loopback (http://127.0.0.1:8080/)
                         │  /v1/… and /graph/api/… with the caller's credentials:
                         │  a token as Bearer, no Cookie; else Basic and Cookie (ADR-03, ADR-10)
                         │  auth_request again, per backing call: Grafana role, Access Role filters
                         ▼
     ┌───────────────────┼──────────────────────┬──────────────────────────────┐
     ▼                   ▼                      ▼                              ▼
  pmm-managed         qan-api2              Grafana rules API             Grafana datasource proxy
  inventory           QAN: filtered by      (ADR-17): folder-scoped,      ──▶ vmproxy: filtered by
  (narrowed by MCP)   Access Roles          no Access Roles;              Access Roles ──▶ VictoriaMetrics
  ──▶ pmm-agent       (Grafana role         narrowed by MCP               metrics and the caller's
  actions (EXPLAIN,   checked first)                                      service list (ADR-08, ADR-09)
  SHOW CREATE TABLE)
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

**Planned changes.** `pmm_inventory` builds its list from the metric series the caller can read instead of the inventory API: it drops address and port and reports each service's `last_seen` (ADR-08, [§9.2](#92-the-callers-service-list)).

| Tool | Returns | Backing API | Kind | Phase |
|---|---|---|---|---|
| `pmm_catalog` | Reference data: the QAN column catalog (phase 3) and the metrics catalog per engine (phase 2b) | None; built into the server | Passive | 3, 2b |
| `pmm_service_health` | The triage signals of one service, summarized, with each one's newest sample time | Datasource proxy: `/api/v1/query_range` | Passive | 2b |
| `pmm_query_metrics` | Instant or range query results, summarized per series | Datasource proxy: `/api/v1/query`, `/api/v1/query_range` | Passive | 2b |
| `pmm_list_metrics` | Metric names by substring search, label names, label values, or series | Datasource proxy: `/api/v1/labels`, `/api/v1/label/{name}/values`, `/api/v1/series` | Passive | 2b |
| `pmm_alerts` | Firing alerts with labels, summary and start time, narrowed to the caller's services | Grafana's folder-scoped rules API through nginx (ADR-17) | Passive | 2b |

`pmm_advisors`, planned for phase 2b, is out of the Tech Preview ([ADR-18](adr/ADR-18-advisors.md), [§7.3](#73-advisors)).

**Configuration** [V]:

| Variable | Default | Notes |
|---|---|---|
| `PMM_ENABLE_MCP` | `false` | Also settable through the settings API (`enable_mcp`); read per request. |
| `PMM_MCP_RAW_SQL` | `false` | Environment only; no API setting. |
| `PMM_MCP_ACTION_TIMEOUT` | `15s` | Bounds the actions of one `pmm_get_explain` or `pmm_get_schema` call; the whole call is bounded by it plus 45 s (`toolTimeoutSlack`, `tools.go:27`). |
| `PMM_DEV_MCP_LOOPBACK_URL` | `http://127.0.0.1:8080/` | Development only. |

---

## 5. Decisions already taken

### 5.1 Recorded as ADRs

| ADR | Decision | Source | Implemented or planned in |
|---|---|---|---|
| [01](adr/ADR-01-in-server-endpoint.md) | `/mcp` lives in pmm-managed, not in a sidecar or a standalone server | Epic | #5942 |
| [02](adr/ADR-02-base-and-port.md) | #5942 is the base; port #4045's query intelligence, not its chat backend or its unbounded polling | Epic, PMM-15529 | #5942, phase 2 |
| [03](adr/ADR-03-api-only-data-path.md) | Data only through the public API on loopback, with the caller's credentials; MCP narrows results to the caller's service list and never widens them | Epic, review of pmm-specs#4 | #5942; narrowing in plans 04, 06, 07 |
| [04](adr/ADR-04-stateless-streamable-http.md) | Streamable HTTP, `Stateless`, on the official Go SDK | Epic, implementation notes | #5942 |
| [05](adr/ADR-05-read-only-tools.md) | Every tool read-only; EXPLAIN never executes the statement; live inspection capped per caller and per replica, and cancelled when a call ends early | Epic, review of pmm-specs#4 | #5942; caps and cancel in plan 02 |
| [06](adr/ADR-06-off-by-default.md) | Off by default; the setting is read per request and doubles as a kill switch | D5, PMM-15528 | #6068 |
| [07](adr/ADR-07-sql-redaction.md) | `PMM_MCP_RAW_SQL=false`; fail-closed masking; QAN dimension values allowed | D9, D10 | #6068, phase 2 |
| [08](adr/ADR-08-inventory-under-access-roles.md) | The service list comes from the metric series the caller can read; the Viewer inventory rules from #5942 are removed | D3, review of pmm-specs#4 | Plan 06 |
| [09](adr/ADR-09-metrics-via-datasource-proxy.md) | Metrics through Grafana's datasource proxy by uid, with that prefix under LBAC | D7, PMM-15533 | #5942 |
| [10](adr/ADR-10-nginx-only.md) | `/mcp` served only through nginx: SDK localhost protection off, loopback-peer check instead; cross-site `Origin` and requests without credentials refused | Implementation notes, review of pmm-specs#4 | #5942, #6068; the rest in plan 02 |

`DECISIONS.md` items not carried into ADRs:
- **D1, D2** (where the contributor's branch lived, how commits are named): superseded by `PMM-MCP-GA` in percona/pmm. The branch rules from PMM-15527 move to [`plans/00-roadmap.md`](plans/00-roadmap.md#branch-and-pr-rules).
- **D4** (Access-Role permissions out of scope for #5942): superseded by ADR-12 and ADR-13.
- **D6** (the contributor's demo environment): not carried. Verification uses throwaway VMs from the PMM QA tooling ([§11](#11-testing-and-verification)).
- **D8** (Streamable HTTP response mode): the SDK default (SSE) stays. Revisit if a client fails to receive streamed responses through nginx.

### 5.2 Implementation notes that stay in the spec

- **Lenient decoding of two QAN responses.** qan-api2 encodes non-finite sparkline floats as the strings `"NaN"` and `"Infinity"`, which the generated Swagger client rejects. `qan:getMetrics` and `qan/metrics:getReport` therefore go through a raw POST into types that accept numeric strings [V]. Remove the workaround when PMM-15535 is fixed.
- **Action polling.** 300 ms initial delay, ×1.5 backoff, 2 s maximum, bounded by `PMM_MCP_ACTION_TIMEOUT`. pmm-agent applies its own fixed 10 s limit per action (`agent/runner/runner.go:42`) [V]. MCP doesn't rely on pmm-agent's concurrency limits: it bounds live inspection with its own caps, one live call per service per replica among them ([§8](#8-phase-3-output-contract), plan 04).

---

## 6. Phase 2: the rest of query intelligence

### 6.1 Resolve first

One internal step turns a `queryid` into the facts every later tool needs: service ID, engine, database or schema, tables and the stored example. It uses `POST /v1/qan/query:getExample` (`QueryExample` carries `service_id`, `service_type`, `schema`, `tables` [V]) plus the metadata `pmm_query_detail` already reads.

A `queryid` alone doesn't name one operation: the same fingerprint can run on several services. A query is identified by `queryid`, service and time window; the engine follows from the service.

MCP is stateless (ADR-04), so the window a model used for one tool doesn't carry over to the next unless the model passes it:
- `pmm_top_queries` and `pmm_query_detail` return a `query_ref` per query: `queryid`, `service_id`, `period_from`, `period_to` (ADR-11).
- `pmm_get_explain` and `pmm_get_schema` accept that `query_ref`, or `queryid` with optional `service_id`, `period_from` and `period_to`. Without a window they use the last hour, as `pmm_top_queries` does, and the result states the window used. A query from yesterday is found by passing its `query_ref`; `queryid` alone is a shortcut for recent queries.
- `service_id` becomes **optional** on `pmm_get_explain` and `pmm_get_schema`.
- Candidates are the services the query was seen on in the window, according to QAN, that are in the caller's service list (ADR-03, ADR-08).
- If `service_id` is given, it must be one of the candidates; otherwise the tool answers `not_found`.
- If it is not given: with exactly one candidate, the tool resolves to it; with several, it answers `invalid_input` and lists them; with none, `not_found`.
- The caller's `service_id` is never used unchecked to fetch a plan.
- `pmm_query_detail` follows the same rule: a `service_id` outside the caller's list answers `not_found`, and without one, QAN rows of services outside the list are dropped.
- A MongoDB explain runs on the example QAN returns for the resolved service and window, and its `service_id` is checked against that service. A MySQL EXPLAIN runs on the statement pmm-managed picks for the resolved service and `queryid`, which ignores the window (`managed/services/agents/actions.go:78`) [V]. An example from another service with the same fingerprint is never used.
- A live MySQL or MongoDB plan is the plan the database would choose now, not the plan it chose during the window; the result says so, in its text and in its structured content. A PostgreSQL plan is the one pg_stat_monitor stored.
- **Without a stored example** (examples turned off, ADR-07, or a statement that left `performance_schema` before pmm-agent sampled it): a MySQL EXPLAIN answers `invalid_input` and asks for `placeholders`, the values of the fingerprint's `?` in order, and `database`; a MongoDB explain answers `no_query_source`. `pmm_get_schema` by `queryid` can't then find the tables: on MySQL it answers like EXPLAIN, and on PostgreSQL, when QAN recorded no `tables`, `no_query_source`.

### 6.2 `pmm_get_schema` from a `queryid`

`pmm_get_schema` takes `queryid` as an alternative to `database` + `tables`.

**Where the table list comes from:**
- **PostgreSQL:** the example's `tables`. pg_stat_monitor sends its relations, and pg_stat_statements parses the query with `pg_query_go` [V].
- **MongoDB:** not supported; `pmm_get_schema` is MySQL and PostgreSQL only and answers `invalid_input` for MongoDB.
- **MySQL:** the QAN agents (perfschema and slowlog) never fill `tables` [V]. So: run `mysql_explain_json`, walk the whole plan tree (`query_block`, `nested_loop`, subqueries, materialized and union nodes) and collect every table entry. Resolve format 1 aliases to real names through Note 1003 in the action output, reading only its code: a quoted string or a comment never yields a name; format 2 entries carry real names already. A table that can't be resolved is listed as unresolved, never guessed, and a name the plan doesn't lead to is never returned.

MySQL discovery is **best effort** and doesn't block the rest of phase 2. Base tables named in the plan are returned. Derived tables, CTEs and names that the alias map can't resolve are listed as unresolved.

**Why not #4045's approach.** The ticket says to read `real_table_name` "out of the EXPLAIN plan rather than parsing SQL". `real_table_name` is not part of the plan: pmm-agent adds it by parsing the SQL text after the last `FROM `, and returns one table only (`agent/runner/actions/common.go:87`, "due to historical reasons we parsing only one table name") [V]. #4045's `extractTablesFromExplainJSON` reads only that field, so it can't return the tables of a join. It is not ported.

**What the plans show [V].** Fixtures captured with `capture.sh` on MySQL 5.7.44, 8.0.46 and 8.4.13 and Percona Server 5.7.44-48, 8.0.46-37 and 8.4.11-11 (`managed/services/mcp/testdata/explain/`, named `<flavor>-<version>-<case>.json`; the two CTE cases are unsupported on 5.7, which has no `WITH`):
- **Format 1 `table_name` is the alias when the statement gives one, else the table name; never the schema,** and no field holds the real name (`mysql-8.0-join-aliases`, `mysql-8.0-schema-qualified`). Names alone mislead: for `FROM a b JOIN b a` the plan lists `a`, the alias of table `b`, then `b` (`*-alias-shadows-table`, every version).
- **Note 1003 in `warnings` (format 1)** is present on every captured version and flavor. Every base table appears in the rewritten query, as `` `shop`.`table` `` plus `` `alias` `` when one was written (`*-join-aliases`, `*-alias-shadows-table`: `` `shop`.`a` `b` ``), so the note disambiguates what the plan cannot. Exceptions to that spelling, which the parser must take: a semi join prints `semi join (`shop`.`orders`)` (`*-subquery-where`); a derived table prints `(/* select#2 */ select … from `shop`.`orders` …) `d``, its base tables in the inner select; and column references elsewhere in the text use `` `shop`.`o`.`id` `` (schema, then alias), so only `FROM` entries name tables. On 5.7 the plan shape and the note are the same as on 8.0.
- **Format 2** (8.4 only, `explain_json_format_version=2`) is a tree of `inputs`. A table leaf has `table_name` = the real table and `schema_name`, plus `alias` only when one was written (`mysql-8.4-v2-alias-shadows-table`: alias `a`, `table_name` `b`). Its `warnings` is empty, so there is no Note 1003 and no alias map is needed.
- **Derived table, format 1:** a join member whose `table_name` is the derived table's alias (`d`), no schema, holding `materialized_from_subquery.query_block` whose `table`s are the base tables (`*-derived-table`, same on 5.7). Format 2: a leaf with `table_name` `d` and no `schema_name`, whose `inputs` are `Materialize`, then the aggregate, then the base-table leaves (`mysql-8.4-v2-derived-table`). `<derivedN>` did not occur: only an aliased derived table was captured, and MySQL used its alias.
- **CTE:** format 1 shows it exactly like a derived table, `table_name` = the CTE name with `materialized_from_subquery` and no CTE flag; only Note 1003 starts with `` with `t` as (…) `` (`mysql-8.0-cte`, `mysql-8.4-cte`). Format 2 has a leaf `table_name` `t` whose materialize input carries `"cte": true` and `operation` "Materialize CTE t" (`mysql-8.4-v2-cte`). A CTE named like a real table (`WITH orders AS (… FROM shop.orders …) … FROM orders JOIN … shop.orders r`) stays a CTE: format 1 lists the `customers` alias, the real `orders` alias, and an `orders` entry with `materialized_from_subquery` (the CTE), and the real `orders` appears again inside that subquery, so a plan `table_name` of `orders` alone is ambiguous. Format 2 has the CTE leaf `table_name` `orders` with no `schema_name`, over a `cte: true` input, "Materialize CTE orders", while the real tables carry `schema_name` (`mysql-8.0-cte-shadows-table`, `mysql-8.4-cte-shadows-table`, `mysql-8.4-v2-cte-shadows-table`, same on Percona Server). A CTE referenced twice was not captured.
- **Union:** format 1 has `union_result` with `table_name` `<union1,2>` and `query_specifications[]`, each holding a `query_block` with its own `table` (`*-union`, same on 5.7). Format 2 has a top node `table_name` `<union temporary>` whose `inputs` hold a `union: true` node, "Union materialize with deduplication", over the branches (`mysql-8.4-v2-union`).
- **`IN (SELECT …)`** is flattened into a semi join on every version, so both tables are ordinary members with no subquery node (`*-subquery-where`).

So: format 1 resolves aliases through Note 1003; format 2 entries carry real names; a derived table or a CTE is recognised by `materialized_from_subquery` (format 1) or an entry with no `schema_name` and a `Materialize` input (format 2), and its name goes to `unresolved`.

### 6.3 `pmm_get_explain` from a `queryid`

With resolve-first, `pmm_get_explain` needs only `queryid`: the engine picks the source (stored plan for PostgreSQL, live action for MySQL and MongoDB), and the database comes from the resolution. `placeholders` and `format` stay. The free-form MongoDB `query` input is removed, so a MongoDB explain runs only on the example QAN stored (ADR-05).

### 6.4 `pmm_get_config` beyond numeric variables

Moved out of the epic. The exporters publish numeric settings only; the tool's own description already says that string-valued knobs such as `sql_mode` are not in metrics [V]. The Grafana datasource proxy can't return what isn't collected. The pt-summary actions would work, but their output includes host names and file paths. PMM-15792 asks the exporters to publish string settings as info metrics; PMM-15529 gets a comment saying why the item left.

### 6.5 Landing order

1. Merge #6099 into `PMM-MCP-GA`.
2. Rebuild #6100 and #6101 on `PMM-MCP-GA` by cherry-pick and retarget them there ([plan 01](plans/01-land-phase-2.md)).
3. The live-inspection caps and cancellation land with the hardening of `/mcp` ([plan 02](plans/02-origin-and-limits.md)).
4. After the contract ([plan 03](plans/03-output-contract.md)), [§6.1](#61-resolve-first) to [§6.3](#63-pmm_get_explain-from-a-queryid) on a new branch from `PMM-MCP-GA` ([plan 04](plans/04-resolve-first.md)).

### 6.6 Acceptance

PMM-15529's criteria stand, with the `pmm_get_config` item removed:
- `pmm_get_explain` and `pmm_get_schema` work from a `queryid` alone.
- `pmm_top_queries` supports `group_by`, label filters, `columns`, `offset` and `search`, and reports total rows.
- A MySQL query that joins N base tables returns all N definitions; derived tables and CTEs are listed as unresolved.
- No `pmm_get_explain` or `pmm_get_schema` call runs longer than `PMM_MCP_ACTION_TIMEOUT` plus 45 s, and its actions stop within `PMM_MCP_ACTION_TIMEOUT`. Every other tool call is bounded by the tool deadline (`PMM_MCP_ACTION_TIMEOUT` plus 45 s), and each of its backing calls by 30 s (`callTimeout`).
- A call that times out or is cancelled leaves none of its actions running on pmm-agent.
- A `service_id` the query was not seen on, or that is not in the caller's service list, returns `not_found`, for `pmm_query_detail` too. A query seen on several services returns `invalid_input` listing only services in the caller's list.
- A third live-inspection call from the same caller, while two are in flight, returns `rate_limited`; so does a ninth on one replica across callers, and a second on a service that already has one in flight on that replica, whoever the callers are.
- A `query_ref` returned by `pmm_top_queries` for a window a day old, passed to `pmm_get_explain` and `pmm_get_schema`, resolves the same service as `pmm_query_detail` did for that window, and for MongoDB the same example. The same `queryid` alone, outside the last hour, returns `not_found` and names the window it searched.

---

## 7. Phase 2b: metrics, alerts and Advisors

Ticket: PMM-15790, under PMM-14247. The tools are passive (ADR-05) and follow the contract ([§8](#8-phase-3-output-contract)). Metrics are filtered by the caller's Access Roles in vmproxy; alerts are narrowed by MCP to the caller's service list (ADR-03), so they come after that list ([§9.2](#92-the-callers-service-list)). Advisor results are out of the Tech Preview ([§7.3](#73-advisors)).

### 7.1 Metrics

Decision: [ADR-15](adr/ADR-15-metrics-tools.md); the caps are in [§8](#8-phase-3-output-contract).

- **Tools.** `pmm_service_health(service_id, period_from, period_to)` returns the triage signals of one service from a fixed map of queries per engine, each with its newest sample time, its source metric, or `no_data`; MCP derives no "stale" state and no verdict. A node signal that is `no_data` while others have data, and a result with every signal `no_data`, each carry a note that an Access Role may hide the series; the second also says the service and its node may have sent nothing in the window. From plan 06, a service that an Access Role hides is outside the caller's service list and answers `not_found`, so the second note says instead that the listed service sent none of these metrics in the window, and that an Access Role can still hide its node's series. `pmm_catalog(kind: metrics, engine)` returns a curated catalog of about 30 to 60 metrics per engine, checked in CI against exporter fixtures. `pmm_query_metrics` runs any instant or range query. `pmm_list_metrics` lists metric names by substring, label names, label values, or the series of a selector.
- **Access Roles** need nothing new: vmproxy injects the caller's filters on all these paths (`vmproxy/proxy/proxy.go:46-50`) [V]. On the label endpoints, VictoriaMetrics honours them unless `-search.ignoreExtraFiltersAtLabelsAPI` is set, and PMM doesn't set it [V]; a test with a restricted role pins this.
- **Execution budget.** Every expression is parsed (`metricsql`, a new dependency) and refused before it reaches VictoriaMetrics unless: every selector, each OR group counted on its own, names a metric; a regex name also has a literal service or node scope; the span of time read, nested lookbehinds summed per path, is within the cap; `@` is absent; no MetricsQL `WITH` template or built-in template (`ttf`, `ru`, `range_median`, `alias`) is used; no function that creates a series per distinct value, or whose output no budget bounds (`count_values`, `count_values_over_time`, `histogram`, `histogram_over_time`, and `aggr_over_time` naming one), is called; no non-ASCII character or backslash stands outside a string; every subquery's step is at least the span read ÷ 2,000, and a rollup over an expression stays within 4,000 points per series; an instant query's root is not a range selector or subquery; and the expression is within the length and selector caps. The span is VictoriaMetrics' own reading of lookbehind: rollup windows, each subquery's range plus two of its steps and 5 minutes, and `offset`s. [tool-contract §8.1](tool-contract.md#81-budgets-of-the-metric-tools) lists the rules. Before a `pmm_query_metrics` query runs, each selector is counted over the span with the `series` endpoint, and one that matches more than the series cap refuses the query, with a hint to narrow and aggregate. List requests carry VictoriaMetrics' `limit`. PMM's own VictoriaMetrics limits (100,000,000 series, 1,500,000,000 samples, 90 s, `supervisord.go:50-55`) [V] are sized for dashboards and are not relied on.
- **Response budget.** Every `pmm_query_metrics` response fits one budget of points and bytes, text and structured content together: summaries by default, a step chosen to fit, the top N series by max, repeated and internal labels left out, non-finite values as `null`, and a narrowing hint built from the caller's expression when a result is cut. MCP reads at most a fixed number of bytes of any VictoriaMetrics response, so no result is decoded whole before the budget applies.
- **Steering.** `Instructions` and the tool descriptions point to the built-in signals, the catalog, and aggregated queries.
- **Concurrency.** Caps per caller and per replica; a further call answers `rate_limited` (ADR-05). `pmm_top_queries` and `pmm_query_detail` share these caps, and their window is capped. One per-replica limit covers every request MCP sends to VictoriaMetrics, from any tool, the service list and the alert list included, and each `pmm_service_health` query takes a slot of it; its size is half of VictoriaMetrics' limit on concurrent queries, at least 1: `VM_search_maxConcurrentRequests` when set, otherwise VictoriaMetrics' own default, `min(2 × CPUs, 16)`. PMM doesn't set `-search.maxConcurrentRequests`. A token bucket per caller limits how often live and metric calls start; its `rate_limited` answer carries `retry_after`.
- **Fleet size.** Plan 05 states the supported fleet size, from the load test (§8).
- All build on `queryMetrics` (`tools_inventory.go:256`), which runs instant queries today [V].

### 7.2 Alerts

Decision: [ADR-17](adr/ADR-17-alerts.md).

- `pmm_alerts` reads the firing alerts from Grafana's rules API through nginx with the caller's credentials. That API is folder-scoped, so `pmm_alerts` shows a Viewer what PMM's own alert page shows; Grafana's alert list endpoints are not folder-scoped and never supply the list. Silence state comes from the Alertmanager, joined by rule UID only. No Grafana alerting API carries an Access Role filter [V]. Plan 07 Task 1 checks this on a Feature Build and records it in ADR-17 before that ADR is accepted.
- MCP keeps an alert that names a service when every service label it carries is in the caller's list, whatever node it names, since PMM's down templates name the pmm-agent's node (`pmm-server` for RDS and Azure services); an alert that names only nodes when they are in the list, which holds services and nodes of every type (ADR-08); and, as Grafana's UI shows them to the same caller, an alert with no service or node label and every alert of PMM's own HA and PMM Server component rules, identified by rule UID or provenance, never by a label. The list used for alerts covers 7 days of `up` samples, not 1 hour, so a service whose pmm-agent went silent keeps its firing alerts, its down alert included, for 7 days ([§13](#13-risks-and-mitigations)). Narrowed, not filtered (ADR-03).
- It returns firing alerts, silenced or not (and until when), with name, severity, labels, summary, description, start time and a link, and filters by service, node and severity. Summaries and descriptions are untrusted text (ADR-11) and never used for narrowing.
- The tool description and every result say "Currently firing alerts only; resolved alerts are not shown." Alert history is a follow-up (ADR-17).

### 7.3 Advisors

Decision: [ADR-18](adr/ADR-18-advisors.md), option 4: `pmm_advisors` is out of the Tech Preview, and plan 07 doesn't build it.

- Advisor texts can carry account details and the security posture of a monitored database, which `pmm_advisors` would send to the model provider as written.
- `GET /v1/advisors/checks/failed` (`checks.go:117`) [V] requires the Editor Grafana role (`auth_server.go:84-86`) [V], and an Editor token in an AI client also carries write access to alerting and to Advisor checks.
- Viewers can already read fleet-wide counts of failed Advisor checks through PMM's metrics; that is accepted.
- ADR-18 keeps the design of the narrowed tool (its option 2) for a later ticket, which needs a new ADR.

### 7.4 Acceptance

- `pmm_service_health` returns its signals for a MySQL, a PostgreSQL and a MongoDB service, one call each; each signal has `last_at` or `no_data`. A signal whose query fails is reported with its code, and the result is `partial`.
- `pmm_catalog(kind: metrics)` returns entries for each engine. The CI test fails when an entry's metric disappears from the exporter fixtures.
- `pmm_query_metrics` answers an instant and a range query. No response exceeds the point and size budget: a result that would is summarized or cut to the top N series, says so, and suggests a narrower query built from the caller's expression. A NaN value arrives as `null`.
- `pmm_list_metrics` with `search: mongodb` returns only names that contain `mongodb`; over the limit, it groups them by prefix with counts. With `search: ".*"` it returns only names containing the literal `.*` (none).
- With an Access Role that allows one service: `pmm_service_health`, `pmm_query_metrics` and `pmm_list_metrics` return only that service's series and label values; `pmm_alerts` returns only that service's alerts, plus alerts with no service or node label and the alerts of PMM's own rules. That service's down alert is among them even when its pmm-agent runs on another node. A Viewer gets no alert of a rule in a folder it can't read.
- A fifth metric call from the same caller, while four are in flight, returns `rate_limited`; so does a ninth on one replica across callers. `pmm_top_queries` and `pmm_query_detail` count against the same caps, and a window over 30 days answers `invalid_input`. A caller whose token bucket is empty gets `rate_limited` with `retry_after` in `_meta`, for live and metric calls alike.
- A VictoriaMetrics response over the size cap fails the call after MCP has read no more than the cap.
- With more requests to VictoriaMetrics than the per-replica limit, from metric tools, health signals and the service list together, no more than the limit are in flight at once.
- These answer `invalid_input` with a hint and never reach VictoriaMetrics: `{__name__=~".+"}`; a selector without a metric name, including one OR group without it; `{__name__=~"mysql_.*"}` without a service or node matcher, or with `service_name=~".+"`; `rate(x[365d])` as an instant query; `[30d:5m]` subqueries; nested subqueries whose lookbehinds add up past the cap; `@`; a range over the cap; an expression over the length or selector cap; a `WITH` template or one of `ttf`, `ru`, `range_median`, `alias`; `count_values("v", x)`, `histogram_over_time(x[5m])` and the other series-per-value functions; `x[5m]` or `x[1h:1m]` as an instant query, with or without `offset`; a non-ASCII character or a backslash outside a string; and a subquery whose step is under the span read ÷ 2,000. A selector that matches more than 2,000 series over the span answers `invalid_input` with a hint after one `series` request per selector, before the query runs.
- **Load on VictoriaMetrics.** On the smallest supported server size, with at least 50 monitored services, five callers each run broad accepted queries in a loop for 10 minutes: `rate(mysql_global_status_questions[5m])` without aggregation over 6 days, an instant query with a 6-day window, and `{__name__=~"mysql_global_status_.*", service_name=~"db1|db2|…"}` naming 10 services. Each caller also runs a `pmm_service_health` loop over 10 services; plan 07 repeats the run with a `pmm_alerts` loop added. Record VictoriaMetrics' CPU and memory, the p95 latency of dashboard queries, and the rule-evaluation failures of Grafana's alerting and VMAlert, with and without that load. Pass: the load adds no rule-evaluation failure, and the dashboard p95 under load is at most twice the baseline; otherwise the caps in §8 are lowered and the test runs again. The services the passing run had are the supported fleet size, stated in §8 and `mcp.md`.

---

## 8. Phase 3: output contract

Decision: [ADR-11](adr/ADR-11-output-contract.md).

1. **One result value, two renderings.** Each tool gets a Go output type, for example `inventoryResult{Services, Total, Offset, Limit, Truncated}`. The handler builds it once; the SDK sends it as `structuredContent` and keeps the text content the handler sets (`mcp/server.go:387-470` in v1.8.0) [V]. How tools are registered, and why, is in item 4. The text, with its "View in PMM" links, is rendered from the same value. For metrics, the text carries the summary table and raw points go only in the structured content (ADR-11).
2. **Redaction on the value.** ADR-07's masking runs on the result value before either rendering, so structured content can't carry what the text withholds. A test runs every tool with `PMM_MCP_RAW_SQL` off and checks both renderings.
3. **Caps and paging.** Every listing tool takes `limit` and `offset` and reports `total`, `offset`, `limit` and `truncated`. The text ends with an explicit marker such as "showing 1–50 of 312; pass offset=50 for more". These are the values the ADRs point to; the token measurement may change them, and this table is where they change:

   | Tool or field | Default | Maximum |
   |---|---|---|
   | `pmm_inventory` services | 50 | 200 |
   | `pmm_top_queries` rows | 10 | 100 (unchanged) |
   | `pmm_get_schema` tables | — | 10 (unchanged) |
   | `pmm_get_config` variables | 200 | 1000 |
   | Plan body | — | 64 KiB, with a truncation marker |
   | One table's DDL | — | 32 KiB, with a truncation marker |
   | `pmm_query_metrics` series shown (top N by max) | 20 | 100 |
   | `pmm_query_metrics` points per response | — | 2,000; the step grows to fit, else summaries |
   | `pmm_query_metrics` response size, text and structured content together | — | 16 KiB; a query that alone fills it is echoed as its first 200 bytes |
   | `pmm_query_metrics` request range | 1 h | — |
   | `pmm_service_health` window | 1 h | just under 7 days: the signals also read about 5 minutes before the window, and a call reads at most 7 days |
   | `pmm_query_metrics` time read: range plus the largest lookbehind path (rollup windows, each subquery's range plus two steps and 5 minutes, `offset`s); a selector read through no window counts one step, and a window shorter than the step counts as one | — | 7 days |
   | `pmm_query_metrics` expression | — | 4 KiB, 10 series selectors (each OR group counts); a regex metric name has a literal prefix of at least 3 bytes and a literal service or node scope; no `@`; no `WITH` or `ttf`, `ru`, `range_median`, `alias` templates; no `count_values`, `count_values_over_time`, `histogram`, `histogram_over_time`, or `aggr_over_time` naming one; no non-ASCII character or backslash outside a string; a subquery's step at least the time read ÷ 2,000; at most 4,000 points per series for a rollup over an expression; an instant query's root is not a range selector or subquery |
   | `pmm_query_metrics` series one selector matches over the time read, counted before the query | — | 2,000 |
   | A VictoriaMetrics response, as MCP reads it | — | 4 MiB |
   | `pmm_list_metrics` names, labels, values or series | 100 | 1000; names over the limit grouped by prefix with counts; series also within 16 KiB |
   | `pmm_list_metrics` look-back | 1 h | 7 days, every `kind` |
   | The caller's service list: look-back of the `up` series (ADR-08) | 1 h | — |
   | The service list that narrows alerts: look-back of the `up` series (ADR-17) | 7 days | — |
   | `pmm_alerts` alerts | 50 | 200 |
   | `pmm_top_queries` and `pmm_query_detail` window | 1 h | 30 days |
   | Supported fleet size | — | the services of plan 05's passing load test, stated here by plan 05 Task 9 |

   Concurrency and timeouts, which are not per response:

   | Limit | Per caller | Per replica | Notes |
   |---|---|---|---|
   | Live-inspection calls in flight | 2 | 8 | A further call answers `rate_limited` immediately (ADR-05). |
   | Live-inspection calls in flight on one service | — | 1 | Per `service_id`, across callers; a further call answers `rate_limited` immediately (ADR-05, plan 04). |
   | Actions in flight within one live-inspection call | — | — | 4 (ADR-05). |
   | Metric and QAN calls in flight | 4 | 8 | One call counts once, however many queries it runs (ADR-15). `pmm_top_queries` and `pmm_query_detail` count too (plan 05). |
   | Requests to VictoriaMetrics in flight | — | half of VictoriaMetrics' concurrent-query limit, at least 1: `VM_search_maxConcurrentRequests` when set, else its default `min(2 × CPUs, 16)` | Every request MCP sends to VictoriaMetrics, from any tool: metric calls, each health signal, the service list, the alert list. A request waits for a slot until its call's deadline (ADR-15, plan 05). |
   | Calls started (token bucket) | live: 10 per minute, burst 4; metric: 60 per minute, burst 10 | — | An empty bucket answers `rate_limited` with `retry_after` in `_meta` (ADR-05, ADR-15, plan 05). |
   | VictoriaMetrics `timeout` argument | — | — | 25 s, below the 30 s timeout of every backing call (`callTimeout`, `client.go:53`). |

4. **Errors.** The codes are those in `errors.go`: `not_found`, `invalid_input`, `unauthorized`, `timeout`, `no_query_source`, `insufficient_privileges`, `agent_unreachable`, `pmm_unavailable` [V], plus `rate_limited` (ADR-05). Each tool's row in `tool-contract.md` lists the codes it can return. How an error is returned, `error: <code>` text plus `_meta.com.percona/error` and no structured content, and why tools are registered with `Out = any`, is in [ADR-11](adr/ADR-11-output-contract.md). `timeout`, `agent_unreachable`, `pmm_unavailable` and `rate_limited` are retryable. An argument the SDK's input schema refuses is answered by the SDK before the tool runs, outside this envelope (plan 03). No error message names a service outside the caller's list, nor echoes a `service_id` or name the caller sent: the text is "not in your service list (services that sent metrics in the last hour)".
5. **Tool-description budget.** Reference data moves out of tool descriptions into one read-only tool, `pmm_catalog(kind, engine)`: the QAN column catalog (`kind: qan_columns`) leaves `pmm_top_queries`' description, and the metrics catalog (`kind: metrics`, ADR-15) never enters one. `pmm_top_queries` keeps its four named rankings (`load`, `total_query_time`, `avg_query_time`, `count`) and says to call `pmm_catalog` for the rest; an unknown column answers `invalid_input` and points to it. The token cost of a standard slow-query triage is measured before and after and recorded on PMM-15530.
6. **`Instructions`.** Updated with each plan that changes the contract: paging and `pmm_catalog` (plan 03), EXPLAIN and schema from a `query_ref` or a `queryid` (plan 04), ADR-15's metrics block (plan 05), alerts (plan 07), and a line that names every kind of untrusted text as data, not instructions, which each plan that adds a kind extends: output-schema marks don't reach every model ([§11](#11-testing-and-verification)).
7. **Provenance, partial results and untrusted text** (ADR-11). A result built from time-based data carries its window; a result about a query, service, alert or check carries its `pmm_url`; both in structured content and text. Query results carry a `query_ref` ([§6.1](#61-resolve-first)). A result from several backing calls marks the parts that failed (`partial: true`) instead of failing whole. Fields whose text comes from monitored databases or users (query text and examples, DDL with comments, label values, alert annotations) are marked untrusted and named in `Instructions`. A caveat the text carries, such as the live-plan label, is in structured content too.
8. **Where the contract lives.** `tool-contract.md` in this folder, which plan 03 creates and the security design review reads ([§3.1](#31-order-from-here)). It holds:
   - the rules every tool follows: the error envelope, paging, provenance, partial results and untrusted fields;
   - one table with a row per tool: minimum Grafana role, backing APIs, whether the data is filtered by Access Roles or narrowed by MCP (ADR-03), passive or live (ADR-05), and the engines it supports, with what it returns for each.

   Inputs and output schemas are not written out by hand. In percona/pmm, a golden-file test snapshots `tools/list` (names, input and output schemas, annotations), so any contract change shows up as a diff in review. Until release, the contract can change freely; after release, only additively, like the proto API.

**Acceptance.**
- Every tool returns structured content that validates against its output schema, and text rendered from the same value.
- A failing call returns an `isError` result with `_meta.com.percona/error` and no structured content, for every tool.
- Every listing tool pages, reports `total` and `truncated`, and ends its text with a truncation marker when cut.
- With `PMM_MCP_RAW_SQL` off, no SQL literal appears in statements, examples, plan strings or agent errors, in either rendering; ADR-07's exceptions (DDL, plan numbers, QAN dimension values, labels, alert and Advisor texts) are tested as exceptions.
- The golden `tools/list` test exists and passes, and the QAN column list is gone from `pmm_top_queries`' description.
- The token cost of the standard triage, before and after, is recorded on PMM-15530.

---

## 9. Phase 4: identity and Access Roles

Goal: metrics and QAN data are filtered by the caller's Access Roles, for interactive users and service-account tokens alike, and MCP narrows everything else to the caller's service list (ADR-03). PMM-15534 is the open ticket this phase depends on; it lands on `main`.

### 9.1 Service-account tokens are principals

Decision: [ADR-12](adr/ADR-12-service-accounts-as-principals.md). PMM-wide, so it lands on `main` through PMM-15534's own PR, and `main` is then merged into `PMM-MCP-GA`.

- The auth path takes the service account's ID from the `GET /api/auth/serviceaccount` response it already fetches for every service token (`client.go:551`) [V]. Percona's Grafana fork answers that route with `ServiceAccountProfileDTO`, whose `id` is the account's user ID (`token.go:115`, `models.go:147`) [V]. No Grafana change, extra call or `serviceaccounts/search` fallback is needed.
- Access Roles assigned to that ID then apply to the token exactly as to an interactive user: the filters on QAN and on metrics, and so the caller's service list ([§9.2](#92-the-callers-service-list)).
- A principal seen for the first time gets the default role, as interactive users do today (`getLBACFilters`, `auth_server.go:482`) [V]. Tokens resolve to user ID 0 today and get no filter (`getAuthUser`, `client.go:291`) [V], so the default role can only narrow what a token sees.
- PMM's node accounts are Admin service accounts (`CreateServiceAccount`, `client.go:668`) [V]. They read the inventory and send metrics and QAN data, and Access Roles filter none of those paths (`lbacPrefixes`, `auth_server.go:181`) [V], so a restricted default role doesn't change what pmm-agent and pmm-admin do.
- Roles are assigned to a service account with the existing `POST /v1/accesscontrol/roles:assign` and the account's ID. The access-control docs say how, in PMM-15534's change; `mcp.md` points to them. A role picker on Grafana's service-account page is out of scope.
- A principal whose identity lookup yields no positive user ID is refused with 401, and Access Role filters are skipped only for the anonymous identity (ADR-12).
- **Dropped from the epic:** propagating the caller's identity from `auth_request` to upstreams (`X-User-ID`, sketched in #4045). Every MCP backing call already passes `auth_request`, which resolves the caller, and MCP needs no identity of its own (ADR-03).

### 9.2 The caller's service list

Decisions: [ADR-08](adr/ADR-08-inventory-under-access-roles.md), [ADR-03](adr/ADR-03-api-only-data-path.md).

- `pmm_inventory` and every service lookup in MCP (`listServices`, `engineOf`, `serviceEngine`, resolve-first) use the services in the metric series of the last hour, read through the Grafana datasource proxy, which vmproxy filters by the caller's Access Roles: `up` grouped by `service_id`, `service_name`, `service_type`, `node_id`, `node_name`, `environment` and `cluster`, with the newest sample time as `last_seen`. Scrape targets carry these labels (`MergeLabels`, `scrape_configs.go:160`) [V].
- The Viewer rules for `GET /v1/inventory/services` and `/nodes` that #5942 added (`auth_server.go:161-167`) [V] are removed; the inventory API stays Admin-only, as on `main`.
- MCP narrows to this list: live actions, resolve-first candidates, `pmm_query_detail`, `pmm_get_config` and alerts. A `service_id` or name outside it answers `not_found` with a fixed text that echoes nothing the caller sent ([§8](#8-phase-3-output-contract) item 4).
- `pmm_inventory` reports each service's `last_seen`, the newest `up` sample time, whatever its value. A target scraped with `up=0` stays listed with a current `last_seen`; a service leaves the list only when no `up` sample at all arrived in the last hour. MCP derives no health state of its own, so it never disagrees with PMM's own service status, which uses other metrics and rules (`managed/services/management/service.go:61-76`) [V].
- A service that QAN shows but that sent no `up` sample in the last hour appears in `pmm_top_queries` (filtered by qan-api2) and answers `not_found` from detail, explain and schema ([§13](#13-risks-and-mitigations)).
- Live inspection and alerts are narrowed, not filtered: not a security boundary (ADR-03). Filtering them by Access Role is PMM-wide work, deferred ([ADR-16](adr/ADR-16-access-roles-on-pmm-apis.md)).
- Trade-offs: no address or port in `pmm_inventory`, and a service with no series in the last hour is not listed ([ADR-08](adr/ADR-08-inventory-under-access-roles.md)).

### 9.3 Access-Role permissions: separate ticket

Decision: [ADR-13](adr/ADR-13-access-role-permissions.md). `mcp:use` as a requirement while Access Control is on, delivered on PMM-15791 after the MCP release. It is governance (who may use MCP), not data scoping, and touches a migration, the proto, the auth path and the role editor (in the Grafana fork today, in the PMM UI after PMM-15744). `inventory:read` is dropped: the service list is already scoped (ADR-08).

### 9.4 Acceptance

- A service-account token resolves to its Grafana user ID. A principal whose identity lookup yields no positive user ID gets 401.
- An Access Role whose filter matches one service, assigned to a service account or to an interactive Viewer: `pmm_inventory`, `pmm_top_queries`, `pmm_query_detail`, `pmm_get_explain`, `pmm_get_schema`, `pmm_get_config` and the metrics tools return only that service's data. `pmm_alerts` returns only that service's alerts, its down alert included when its pmm-agent runs on another node, plus those with no service or node label and the alerts of PMM's own rules.
- With that role, one `queryid` recorded on the allowed service and on a hidden one: `pmm_query_detail`, `pmm_get_explain` and `pmm_get_schema` resolve to the allowed service; given the hidden service's `service_id`, they return `not_found`, and no error names it. For PostgreSQL stored plans this holds once PMM-15697 is fixed ([§10](#10-phase-5-release)).
- Two services on one node, a role that allows one of them: the other service and its alerts are hidden.
- A Viewer token gets `unauthorized` from `GET /v1/inventory/services`.
- With a restricted default role, a registered node's own account still lists, removes and unregisters its services with `pmm-admin`, and `pmm-agent setup` finds its node. PMM-15534's PR tests this on `main`; plan 06 repeats it after merging `main`.
- With Access Control off, or a role without a filter: every service with metrics, as on dashboards.

---

## 10. Phase 5: release

1. **One merge back, shortly before the release branch is cut.** On `main` since PMM-15472 (checked at `07e6237eb`; re-checked before the merge), user docs publish from the release branch, but `documentation/api/` (the API reference, `welcome/mcp.md` included) syncs to the public reference on every push to `main` (percona/pmm `AGENTS.md`, `api-docs.yml`), so `PMM-MCP-GA` merges into `main` just before the release that ships it is cut. Before that: phases 2, 2b, 3 and 4 are merged into `PMM-MCP-GA`, the implementation review has passed, `main` is merged in, `make gen` regenerates generated files (never hand-merged), and CI and a Feature Build are green. After it, the branch is deleted.

   **Release gate**, by ticket key:
   - PMM-15534 (ADR-12) is fixed on `main` and merged into `PMM-MCP-GA`;
   - PMM-15697 is fixed, or the implementation review accepts in writing that PostgreSQL stored plans are not yet filtered;
   - PMM-15702 is fixed, or the implementation review accepts in writing that QAN tools fail for Access Roles whose filter values contain a quote or a colon;
   - the implementation review has assessed PMM-15339, PMM-15703, PMM-15715 and PMM-15838 for their effect on MCP.
2. **Security review, in two passes.** A design review of this folder and `tool-contract.md` before plans 04 to 07, which took place on 2026-11-06 ([§3.1](#31-order-from-here)), and an implementation review before the merge back. Scope of both:
   - `/mcp` served only through nginx, the Origin check, and the refusal of anonymous callers (ADR-10);
   - credentials: which header wins, forwarding `Authorization` and `Cookie` over loopback, that no hop on the path logs them at any log level, and the caller key (ADR-03, ADR-05, ADR-10);
   - `/mcp` at `viewer`; the caller's service list and MCP's narrowing, including that for live inspection and alerts it is not a security boundary (ADR-03, ADR-05, ADR-08, ADR-17);
   - model-written metric queries and their limits (ADR-15);
   - service-account tokens under Access Roles (ADR-12);
   - live inspection a Viewer can start, including live EXPLAIN, its caps and cancellation (ADR-05);
   - redaction across text and structured content (ADR-07, ADR-11);
   - the sensitivity of EXPLAIN output, DDL, and QAN dimension values such as user and client host.

   Findings are closed or accepted in writing.
3. **Default state.** Decision: [ADR-14](adr/ADR-14-default-state.md). Off in the release that lands `PMM-MCP-GA`, on new and upgraded servers alike. A later ADR decides the default for the release that drops the Tech Preview label.
4. **Tool-usage telemetry and operator metrics.** In pmm-managed: a counter `pmm_managed_mcp_tool_calls_total{tool, code}`, where `code` is `ok` or one of the error codes; a histogram `pmm_managed_mcp_tool_duration_seconds{tool}`; and a gauge `pmm_managed_mcp_tool_calls_in_flight{tool}`. The existing `pmm-managed` scrape job carries them into VictoriaMetrics (`scrape_configs.go:83`) [V], so operators can see MCP's load next to VictoriaMetrics' own. Telemetry reads only the counter: one new item in `managed/services/telemetry/config.default.yml` reads 24-hour totals per tool and code through the `VM` data source [V], plus whether MCP is enabled. No arguments, queries, service names or users are recorded.
5. **percona/pmm-mcp.** Archive it with a README that points to `/mcp`, and close its two contributor PRs with thanks and the reason (ADR-01).
6. **Docs.** `documentation/docs/api/mcp.md` and `documentation/api/welcome/mcp.md` go live with the release, plus a release-notes entry: what it is, that it is off by default and how to enable it, how Access Roles apply to service-account tokens, and that `pmm_inventory` lists services from their metrics.

---

## 11. Testing and verification

Every phase:
- Unit tests next to the code, fixtures under `managed/services/mcp/testdata/`.
- From phase 3, the golden `tools/list` test.
- `api-tests/mcp` against a live server.
- For user-visible changes, a PMM Server built from the branch (the live-check environment in [plans/00](plans/00-roadmap.md#how-to-execute-these-plans)): the Viewer-token triage from PMM-15528 (`pmm_inventory` → `pmm_top_queries` → `pmm_query_detail` → `pmm_get_explain` → `pmm_get_schema` → `pmm_get_config`), and `POST /mcp` answering 404 when the endpoint is off.

Additionally:
- **Origin check (ADR-10):** a cross-site `Origin` gets 403; a request without `Origin` is served; a non-loopback peer gets 404; a backing call carries the caller's credentials in ADR-10's canonical form.
- **Hardening (plan 02):** the caps on live inspection, and that a call that times out leaves no action running.
- **Phase 2:** MySQL EXPLAIN fixtures from each supported version, and a multi-table join on a live server.
- **Phase 3:** the acceptance in [§8](#8-phase-3-output-contract), and the golden `tools/list` test.
- **Phase 2b:** the built-in signals and the metrics catalog against exporter fixtures; the response budget on a result with 300 series, with its narrowing hint; summaries; the execution budget's refusals; the load test on VictoriaMetrics ([§7.4](#74-acceptance)); `rate_limited` for metric calls; alerts on a server with firing alerts, narrowed for a restricted caller.
- **Phase 4:** the Access Role matrix over every tool ([§9.4](#94-acceptance)): Access Control on and off; interactive Viewer, Editor, service token and Admin; a role that allows one service, two roles with different filters, a negative filter, and the default role; two services on one node; alerts with and without service labels; PMM's node accounts under a restricted default role.
- **Phase 5:**
  - Clients: Claude Code and Cursor against a Feature Build, with a service-account token, at whatever protocol version each sends; a scripted go-sdk client covers each version the SDK negotiates. For each client, record whether it passes `Instructions`, structured content and output schemas to the model; Claude Code doesn't pass output schemas (measured 2026-11-06). Go SDK v1.8.0 supports 2024-11-05 to 2026-07-28 and defaults to 2026-07-28 (`mcp/shared.go:50`) [V].
  - Engines: the triage on MySQL, PostgreSQL and MongoDB, recorded as a tool-by-engine table in `tool-contract.md`.
  - Failure: a pmm-agent that is down (`agent_unreachable`), an expired token (`unauthorized`), and pmm-managed restarting mid-call.
  - AI-client behaviour: the same triage repeated in a loop, and three investigations in parallel with different tokens, for 10 minutes. Record `rate_limited` answers, the load on the monitored databases and on VictoriaMetrics, and whether every response stayed within its budget.
  - HA: one failover check before the merge back. With `Stateless`, a failover is expected to lose only the calls in flight [I].

---

## 12. Corrections to the tickets

| Ticket | Says | Correction |
|---|---|---|
| PMM-14247 | Phases 0 to 5 | Phase 2b added: metrics and alerts (ADR-15, ADR-17), PMM-15790; Advisor results stay out of the Tech Preview (ADR-18). |
| PMM-14247 | Access Roles applied by MCP's backing APIs | MCP narrows alerts to the caller's service list (ADR-03); Access Roles on PMM's own APIs are deferred (ADR-16). |
| PMM-15527, PMM-15528 | In Progress | Both are merged into `PMM-MCP-GA`; close them or list what is left. |
| PMM-15529 | Read `real_table_name` "out of the EXPLAIN plan" | It is parsed from SQL text, one table only; walk the plan instead ([§6.2](#62-pmm_get_schema-from-a-queryid)). |
| PMM-15529 | ~90-column catalog | 76 columns, kept in step with qan-api2 by a test [V]. |
| PMM-15529 | Extend `pmm_get_config` past numeric variables through the datasource proxy | Not possible on that path; moved to PMM-15792 ([§6.4](#64-pmm_get_config-beyond-numeric-variables)). |
| PMM-15529 | `pmm_get_explain` and `pmm_get_schema` from a `queryid`, as one requirement | Resolved only to a single service the caller can see; MySQL tables best effort ([§6.1](#61-resolve-first), [§6.2](#62-pmm_get_schema-from-a-queryid)). Built after the contract ([§3.1](#31-order-from-here)). |
| PMM-15530 | Contract spec in percona/pmm `dev/docs/managed/mcp-tool-contract.md`, after phase 2 | `tool-contract.md` in this folder, written before the rest of phase 2. |
| PMM-15530 | Ship the triage playbook in `Instructions` | It exists; phase 3 updates it. |
| PMM-15531 | Identity design in percona/pmm `dev/docs/managed/` | ADR-12 and ADR-08 here. |
| PMM-15531 | Check the fork's response for an ID, else search by name | The response carries `id`; no search needed. |
| PMM-15531 | Propagate caller identity (`X-User-ID`) | Dropped from the epic ([§9.1](#91-service-account-tokens-are-principals)). |
| PMM-15531 | Evaluate the permissions proposal: adopt, defer or drop | Adopted as requirements under Access Control, without a built-in role (ADR-13), on PMM-15791 after the MCP release. Phase 4 builds the caller's service list from filtered series instead (ADR-08). |
| PMM-15536 | Let Viewers read `GET /v1/inventory/services` and `/nodes` | Not needed by MCP: its service list comes from filtered series (ADR-08). A PMM-wide choice outside the epic. |
| PMM-15532 | Decide the GA default on evidence | Off for this release (ADR-14); a later ADR decides when the Tech Preview label goes. |

---

## 13. Risks and mitigations

- **MCP's narrowing is not a security boundary** for live inspection (EXPLAIN, DDL, indexes) and for alerts: both are narrowed, not filtered (ADR-03). A restricted caller still reads alerts, unfiltered by Access Roles, through Grafana's API and UI. *Accepted* for the Tech Preview; the fix is PMM-wide (ADR-16, deferred), and the implementation review signs off on it.
- **Advisor results stay out of MCP** (ADR-18): their texts can carry account details and security posture, and the Editor token they need can also write alerting and Advisor checks. *Accepted*: a triage through MCP doesn't see failed checks; PMM's Advisors page still shows them.
- **Model-written metric queries** load PMM's own VictoriaMetrics, whose limits (§7.1) are sized for dashboards and don't bound an AI client in a loop. *Mitigation:* the execution budget with its series cap per selector, the bounded read of every response, the caps per caller and per replica, one limit on every request MCP sends to VictoriaMetrics, the rate per caller, and the load test on the smallest supported size with a pass threshold (ADR-15).
- **Caps are per token or session and per replica, not per user** (ADR-05). A service account with several tokens, or an HA cluster, gets more. *Accepted*; the per-replica caps and the per-service cap bound the total. They protect load, not fairness: one principal can hold several caller keys. Revisit with plan 06.
- **The service list depends on metrics** (ADR-08). A service with no series in the last hour is not listed. Alerts use a 7-day list, so a silent agent's alerts, its down alert included, stay for 7 days. *Accepted*: `last_seen` shows how fresh each entry is; a longer look-back for every tool would make the query behind every call read more, and plan 06 records the cost of the 1-hour, 24-hour and 7-day lists.
- **Catalog drift.** The built-in signals and the metrics catalog follow exporter metric names. *Mitigation:* the fixture tests catch renames, at the cost of keeping the fixtures current.
- **A renamed Metrics datasource** breaks the metric reads (ADR-09). *Accepted*; the tools answer `pmm_unavailable` and say why.
- **Untrusted text reaches the model.** Query text, DDL comments, labels and alert annotations can carry injected instructions. *Mitigation:* `Instructions` name every kind of untrusted text, the contract marks them for clients that read output schemas, and `mcp.md` warns against combining `/mcp` with unattended tools that can send data out of the client; none of this stops a client that acts on them, and every tool is read-only (ADR-05).
- **No per-user MCP switch until ADR-13 ships.** With Access Control on, every Viewer and above can use MCP once an admin enables it. *Accepted*; Access Roles still scope what each sees.
- **A long-lived branch in a repository with generated code.** *Mitigation:* `*.pb.go` and Swagger conflicts are resolved by regenerating, never by hand (roadmap); PMM-wide changes land on `main` through their own tickets, not on the branch.
- **Live inspection under an AI-client loop.** *Mitigation:* the caps, one live call per service per replica, and cancellation when a call ends early (ADR-05). A MongoDB explain still runs its candidate plans, on the stored example only.
- **Response size.** Structured content repeats the text's data. *Mitigation:* the phase 3 token measurement covers both before the caps are fixed.
- **Credentials pass through pmm-managed in memory** (ADR-03). *Requirement:* no hop on `/mcp`'s path logs credentials, at any log level, and a test enforces it: plan 04's test covers MCP's own log output, and the implementation review checks the rest of the path.
- **A front proxy that isn't on loopback** makes `/mcp` answer 404, like a disabled endpoint (ADR-10). *Accepted*; `mcp.md` says so.
- **HA failover is untested** [I]. *Mitigation:* one failover check before the merge back ([§11](#11-testing-and-verification)).
- **VictoriaMetrics is on the path of every tool call**, because the caller's service list comes from it (ADR-08). *Accepted*: when it fails, the tool answers `pmm_unavailable`, never an unfiltered list.
- **Services QAN shows but the list lacks** (no `up` sample in the last hour) appear in `pmm_top_queries` and answer `not_found` from detail, explain and schema. *Accepted*; the error text says the list holds services that sent metrics in the last hour.

**Open design questions, raised in the second review of pmm-specs#4.** Each is settled in the plan named, or accepted in writing by the implementation review:
- **Load on pmm-agent.** Settled by the security design review: MCP holds at most one live call per service per replica (plan 04).
- **Requests that reach VictoriaMetrics.** Settled by the security design review: one per-replica limit on every request MCP sends to VictoriaMetrics, at half of VictoriaMetrics' own limit on concurrent queries (PMM doesn't change that limit), and a load test with a pass threshold (plan 05).
- **Fleet size.** Settled by the security design review: a cap on the series one selector matches, and a supported fleet size stated from the load test (plan 05).
- **QAN and ClickHouse load.** Settled by the security design review: the QAN tools share the metric-call caps, with a 30-day window (plan 05).
- **MetricsQL `WITH` templates.** Settled by the security design review: refused (plan 05).
- **The Editor token** `pmm_advisors` would need. Settled by the security design review: `pmm_advisors` is out of the Tech Preview (ADR-18).
- **Comments in SQL fingerprints.** Settled: with raw SQL off, fail-closed masking masks the text of comments in fingerprints (`maskSQLLiterals`, `redact.go`) [V]. `pmm_query_detail`'s `example` isn't masked the same way yet: see the follow-ups below.
- **Clients that need OAuth.** `/mcp` takes static tokens only; MCP's OAuth flow and protected-resource metadata are not supported, and `mcp.md` recommends token expiry (plan 08).

**Follow-ups from the security design review.** Each is built in a plan before the implementation review, or accepted in writing by it:
- `pmm_top_queries` escapes `%` and `_` in `search`, and with `PMM_MCP_RAW_SQL` off, a `search` drops the rows whose fingerprint is withheld.
- `pmm_query_detail`'s `example` is masked like `fingerprint`, numbers and comment text included.

**Open questions, settled before the ADRs that depend on them are accepted:**
- what a Viewer gets from Grafana's rules API, the silence join by rule UID, and whether the rules API identifies PMM's own rules by UID or by provenance (ADR-17, plan 07 Task 1);
- how MongoDB's default explain verbosity behaves across supported versions (ADR-05);
- how `http.CrossOriginProtection` answers MCP clients that send `Origin` without `Sec-Fetch-Site`, behind nginx (ADR-10).

---

## 14. Security-sensitive items

- **Internal tickets**, referenced by key only; their details stay in Jira until they are fixed, as `SECURITY.md` and this repository's rules require: PMM-15339, PMM-15703, PMM-15715, PMM-15838.
- **Public tickets** this work depends on: PMM-15534 (service-account tokens and Access Roles, ADR-12), PMM-15697 (Access Roles on QAN details, examples and plans), PMM-15702 (Access Role filters with quotes or colons in QAN).
