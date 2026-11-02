# Plan 08: Release (task level)

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans).

**Goal:** Land `PMM-MCP-GA` on `main` once, for the PMM release that ships it, with the endpoint off by default, after the implementation security review, the AI client, engine, failure and HA checks, telemetry, and docs.

**Architecture:** No new tool surface. This plan measures, reviews, instruments and ships what plans 01 to 07 built.

**Tech Stack:** Go 1.27, go-sdk v1.8.0, Prometheus client in pmm-managed, PMM telemetry (`managed/services/telemetry`).

**Spec:** [spec §10, §11](../spec.md#10-phase-5-release), [ADR-14](../adr/ADR-14-default-state.md), [ADR-01](../adr/ADR-01-in-server-endpoint.md). Ticket PMM-15532.

## Global Constraints

- `PMM_ENABLE_MCP` and `PMM_MCP_RAW_SQL` stay `false` on new and upgraded servers (ADR-14).
- `PMM-MCP-GA` merges into `main` once, in Task 8, after plans 01 to 07, the security review and the release gate. Generated files are regenerated, never hand-merged.
- **The merge is timed with the release that ships MCP**, and the docs go in with it, not in a separate PR later:
  - On `main`, a push still publishes `documentation/api/` and the Swagger spec to the public API reference (`.github/workflows/api-docs.yml`). `PMM-MCP-GA` changes both: `documentation/api/welcome/mcp.md` and the `enable_mcp` setting.
  - The user docs under `documentation/docs/`, `mcp.md` and the release notes included, are published from the release branch of the latest GA version, so they stay private until the release (percona/pmm `AGENTS.md:245` and `.github/workflows/documentation.yml` on `main` at `07e6237eb`, since PMM-15472). On `PMM-MCP-GA` at `826945906` the older workflow still deploys from `main`; Task 8 re-checks both rules on the `main` it merges into.
- **Telemetry sends two items:** per tool and result code, the number of calls in the last 24 hours; and whether MCP is enabled. Nothing else: no arguments, queries, service names, users or tokens.
- Recording evidence on Jira needs no approval. Posting outside percona/pmm (percona/pmm-mcp's README, its pull requests, archiving it) needs the go-ahead of the PMM product manager, recorded on PMM-15532.
- Branch `PMM-15532-release`, cut from `PMM-MCP-GA`, for Task 5's code and Task 6's docs; one PR into `PMM-MCP-GA` (00). Task 8 is the merge of `PMM-MCP-GA` itself.

## Review Focus

- **pmm-managed restarting in the middle of a call:** the AI client gets an `isError` result with a retryable code, or HTTP 502 from nginx, and the next call succeeds once `GET /v1/server/readyz` answers 200 (Task 3).
- **An AI client that doesn't pass `Instructions` or structured content to its model** still completes the triage from the text alone (Task 2).
- **HA failover during an investigation:** with the stateless transport, the next call succeeds on the new leader (Task 4).
- **The merge back missing a commit from `main`:** `git rev-list --count origin/PMM-MCP-GA..origin/main` is `0` right before the merge (Task 8).
- **A release-gate ticket still open at the merge:** Task 8 checks each key before it starts.

---

### Task 1: Implementation security review

**Files:** none in percona/pmm; findings on PMM-15532.

**Interfaces:** none.

**Steps:**
- The implementation review ([00](00-roadmap.md#terms)) runs after Tasks 5 and 6 are merged into `PMM-MCP-GA`, so it covers the telemetry and the final docs too.
- Scope: spec §10's list, against the code on `PMM-MCP-GA`, with at least:
  - `/mcp` served only through nginx, and the Origin check (ADR-10);
  - anonymous access: `auth_request` refuses `/mcp` with 403 to every caller Grafana resolves as anonymous, one that sends only a junk cookie included (ADR-10, plan 02);
  - credentials: which header wins when a request carries both `Authorization` and `Cookie` (ADR-10), their forwarding over loopback, and that they are never logged (ADR-03); the caller key ([00](00-roadmap.md#terms), plan 02) and the per-caller limits it keys (ADR-05);
  - the caller's service list from Access-Role-filtered series, every service lookup built on it (ADR-08, plan 06), and service-account tokens under Access Roles (ADR-12, PMM-15534);
  - MCP's narrowing of alerts and Advisor results: it is consistency, not a security boundary, because the same caller reads both APIs unfiltered (ADR-03, ADR-17, ADR-18); and the Editor token `pmm_advisors` needs (ADR-18);
  - model-written metric queries, their execution and response budgets, and plan 05's load-test numbers (ADR-15);
  - live inspection a Viewer can start, its limits, and the cancelling of abandoned actions (ADR-05);
  - redaction across text and structured content (ADR-07, ADR-11);
  - the sensitivity of EXPLAIN output, DDL, QAN dimension values, alert annotations and Advisor findings sent to a model provider;
  - the release-gate tickets of Task 8, by key.
- Every finding is closed or accepted in writing on PMM-15532.
- **When a review asks for changes:**
  - A code finding gets its own ticket under the epic, named by key only when it is security-sensitive. It is fixed on its own branch from `PMM-MCP-GA`, with a PR into it, and the reviewer re-checks it.
  - A design finding first changes `spec.md` or an ADR through a pmm-specs PR; the affected plan is updated before its code changes.
  - The design review before plans 04 to 07 (00) follows the same path.
  - Task 8 waits until every finding is closed or accepted.

### Task 2: AI client and protocol matrix

**Files:**
- Create: `api-tests/mcp/protocol_test.go`
- Modify: pmm-specs `tickets/PMM-14247-mcp/tool-contract.md` (engines column)

**Interfaces:** none.

**Steps:**
- **Scripted, per protocol version.** `TestProtocolVersions` loops over go-sdk v1.8.0's `mcp.SupportedProtocolVersions()` (2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25, 2026-07-28). For each version it connects with `mcp.ClientSessionOptions{ProtocolVersion: v}` and a Viewer service-account token, lists the tools and calls `pmm_version`. go-sdk uses `initialize` up to 2025-11-25 and `server/discover` for 2026-07-28. Every version succeeds and reports the version it negotiated.
- **Real AI clients.** Claude Code and Cursor, current versions, against the live-check environment (00) with a Viewer service-account token, at whatever protocol version each sends. Record the version, and whether each client passes `Instructions` and structured content to its model.
- **Text alone.** `TestTriageFromText` in the same file runs the triage as an AI client that ignores `Instructions` and structured content: it reads only each result's text, takes a `service_id` from `pmm_inventory` and a `queryid` from `pmm_top_queries`, then calls `pmm_query_detail`, `pmm_get_explain`, `pmm_get_schema` and `pmm_get_config` with them. Every call succeeds.
- **Engines.** The triage on MySQL, PostgreSQL and MongoDB. Record what each tool returns per engine in the engines column of `tool-contract.md`'s tool table, through a pmm-specs PR.

### Task 3: Failure and AI client behaviour checks

**Files:** none; evidence on PMM-15532.

**Interfaces:** none.

**Steps:**
- **Failures.** On the live-check environment (00):
  - pmm-agent of the inspected service stopped: `agent_unreachable`;
  - an expired token: `unauthorized`;
  - pmm-managed restarted while a `pmm_get_schema` call is in flight: the call ends with an `isError` result with a retryable code, or with HTTP 502 from nginx; the next call, once `GET /v1/server/readyz` answers 200, succeeds.
- **AI client behaviour.** The same triage in a loop, and three investigations in parallel with different tokens, for 10 minutes. Record:
  - the number of `rate_limited` answers;
  - the load on the monitored databases and on VictoriaMetrics, including the service-list query every tool runs (plan 06);
  - whether every response stayed within its budget (spec §8).
  Record on PMM-15532.

### Task 4: HA failover

**Files:** none; evidence on PMM-15532.

**Interfaces:** none.

**Steps:**
- Environment: a PMM HA deployment with three replicas on Kubernetes, built from the branch. Percona engineers use a throwaway k3s cluster from the PMM QA tooling.
- Start an investigation, fail the leader over, and continue. The next call succeeds on the new leader; a call in flight during the failover ends as in Task 3.

### Task 5: Telemetry and operator metrics

**Files:**
- Modify: `managed/services/mcp/` (`Params`, metrics around `addTool`), `managed/cmd/pmm-managed/main.go` (`mcp.New`, `:1268` on `PMM-MCP-GA`), `managed/services/telemetry/config.default.yml`
- Test: `managed/services/mcp/` (metrics test), `managed/services/telemetry/config_test.go`

**Interfaces:**
- Metrics in pmm-managed's `pmm_managed` namespace, as its other metrics (`prometheusNamespace` in `managed/services/checks/checks.go:68`): `pmm_managed_mcp_tool_calls_total{tool, code}`, where `code` is `ok` or an error code; `pmm_managed_mcp_tool_duration_seconds{tool}`; `pmm_managed_mcp_tool_calls_in_flight{tool}`. The existing `pmm-managed` scrape job collects them (`scrape_configs.go:83`).
- Registration: `mcp.Params` gains `Registerer prometheus.Registerer`, and `New` registers the three metrics on it when it is set. `main.go` passes `prom.DefaultRegisterer`, like its other collectors; tests pass `prometheus.NewRegistry()`, so tests never share the global registry.
- Two telemetry items, in the format of the existing ones:

  ```yaml
  - id: MCPToolCalls
    source: VM
    query: sum by (tool, code) (increase(pmm_managed_mcp_tool_calls_total[24h]))
    transform:
      type: JSON
      metric: "mcp_tool_calls_24h"
    summary: "MCP tool calls in the last 24 hours, per tool and result code"
    data:
      - metric_name: 1
        label: "tool"
      - metric_name: 2
        label: "code"
      - metric_name: 3
        value: 1

  - id: PMMServerMCPEnabled
    source: PMMDB_SELECT
    query: (CASE WHEN settings->'mcp'->>'enabled' = 'true' THEN '1' ELSE '0' END) AS mcp_enabled FROM settings
    summary: "MCP endpoint enabled"
    data:
      - metric_name: "pmm_server_mcp_enabled"
        column: "mcp_enabled"
  ```

  `PMM_ENABLE_MCP` is written to the settings table at startup, so the second item covers both ways of enabling MCP.

**Steps:**
- Tests: on a fresh registry, the counter after a success and after each error code; the histogram and the gauge around one call; `config.default.yml` parses with both items.
- Implement; run `go test ./managed/services/mcp/... ./managed/services/telemetry/...`.
- Commit `PMM-15532 Count MCP tool calls for operators and telemetry`.

### Task 6: Docs and release notes

**Files:**
- Modify: `documentation/docs/api/mcp.md`, `documentation/api/welcome/mcp.md`
- Modify, or Create if the branch's base lacks it: `documentation/docs/release-notes/next.md`. It is on `main` at `07e6237eb`, not on `PMM-MCP-GA` at `826945906`; merging `main` in first brings it, else it starts from `documentation/resources/release-notes-template.md`.

**Interfaces:** none.

**Steps:**
- `mcp.md` and `welcome/mcp.md` final: off by default and how to enable it; a Viewer service-account token covers every tool except `pmm_advisors`, which needs an Editor token; results follow the caller's Access Roles, with a link to the access-control docs from PMM-15534; alerts and Advisor results are narrowed to the caller's services for consistency, while Grafana and the Advisors page show the same user everything.
- The release-notes entry goes in `next.md`, which the release-candidate job turns into the version's page (percona/pmm `documentation/AGENTS.md:190-192` on `main`): what MCP is (Tech Preview), that it is off by default and how to enable it, Access Roles and service-account tokens (PMM-15534), and that `pmm_advisors` needs an Editor token.
- Commit `PMM-15532 Finish the MCP docs and release notes`. Then the last step of the plan's PR (00): merge `origin/PMM-MCP-GA` into the branch, with `PMM-MCP-GA` behind 0; run a Feature Build from the branch, verify live, and open the PR `PMM-15532 Instrument and document MCP for the release` into `PMM-MCP-GA`.

### Task 7: percona/pmm-mcp

**Files:** percona/pmm-mcp `README.md`.

**Interfaces:** none.

**Steps:**
- With the PMM product manager's go-ahead: a README that points to `/mcp`; close the repository's two contributor PRs with thanks and the reason (ADR-01); a repository admin archives it.

### Task 8: Merge back

**Files:** none; the merge of `PMM-MCP-GA` into `main`.

**Interfaces:** none.

**Preconditions (release gate, spec §10, by key):**
- PMM-15534 fixed on `main` and merged into `PMM-MCP-GA`;
- PMM-15697 fixed, or PostgreSQL stored plans accepted in writing by the security review;
- PMM-15339, PMM-15703, PMM-15715 and PMM-15838 reviewed by the security review;
- every Task 1 finding closed or accepted in writing; Tasks 2 to 7 done, with their evidence on PMM-15532; any change merged into `PMM-MCP-GA` after the implementation review reviewed by the same reviewer;
- the docs rules re-checked on the `main` being merged into: `documentation/docs/` still published from the release branch (`AGENTS.md`, `.github/workflows/documentation.yml`), and `documentation/api/` still synced on push (`.github/workflows/api-docs.yml`). If either has changed, this task's timing and the open question below are settled again before the merge.

**Timing:** the PMM release that ships MCP is agreed with the PMM release manager and recorded on PMM-15532. The release-candidate job cuts that release's `pmm-X.Y.Z` branch from `main` (percona/pmm `documentation/AGENTS.md:192` on `main`), so the merge is made shortly before that cut.

**Open question for the expansion:** whether `documentation/api/welcome/mcp.md` may go live on the public API reference at the merge, ahead of the release, or is left out of the merge and added to `main` at GA. The release manager decides; Task 6's text is the same either way.

**Steps:**
- Merge `main` into `PMM-MCP-GA`, run `make gen`, get CI and a Feature Build green, and check that `PMM-MCP-GA` is behind 0.
- Open the PR `PMM-MCP-GA` → `main`, titled `PMM-14247 Add the MCP endpoint (Tech Preview)`, its description listing every PR merged into `PMM-MCP-GA`. Merge it with **Squash and merge**, percona/pmm's merge method (`dev/docs/process/GIT_AND_GITHUB.md:54`); each ticket's history stays in its own PR. Delete the branch.
- Regression on a `main` build: the triage with `PMM_ENABLE_MCP=true`, and `POST /mcp` answering 404 with the default.
- Jira, with links to the PRs:
  - close PMM-15527 to PMM-15532, PMM-15790 and the epic PMM-14247;
  - PMM-15534 was closed by its own PR on `main`; check that it is;
  - PMM-15536: comment that MCP no longer needs Viewer inventory reads (ADR-08), and unlink it from the epic; whether Viewers read the inventory stays a PMM-wide choice outside this epic;
  - PMM-15791 (ADR-13) and PMM-15792 stay open; neither is part of this release.
