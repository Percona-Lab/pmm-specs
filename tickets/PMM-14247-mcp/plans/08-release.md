# Release Implementation Plan (task level)

> **For agentic workers:** This plan is task-level. When its step starts ([00](00-roadmap.md)), expand it to full depth with superpowers:writing-plans, then execute with superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Land `PMM-MCP-GA` on `main` once, with the endpoint off by default, after the implementation security review, the client, engine, failure and HA checks, telemetry, and docs.

**Architecture:** No new tool surface. This plan measures, reviews, instruments and ships what plans 01 to 07 built.

**Tech Stack:** Go 1.27, Prometheus client in pmm-managed, PMM telemetry (`managed/services/telemetry`), CHAOS VMs and k3s, Feature Builds.

**Spec:** [spec §10, §11](../spec.md#10-phase-5-release), [ADR-14](../adr/ADR-14-default-state.md), [ADR-01](../adr/ADR-01-in-server-endpoint.md).

## Global Constraints

- `PMM_ENABLE_MCP` and `PMM_MCP_RAW_SQL` stay `false` on new and upgraded servers (ADR-14).
- `PMM-MCP-GA` merges into `main` once, after plans 01 to 07 and the security review; generated files are regenerated, never hand-merged.
- Telemetry records only tool name and result code: no arguments, queries, service names or users.
- Posting on GitHub (percona/pmm-mcp) and Jira is done with the owner's go-ahead.

## Review Focus

- **pmm-managed restarting in the middle of a call:** the client gets a clean error and a retry succeeds (Task 3).
- **A client that doesn't pass `Instructions` or structured content to its model** still completes the triage from the text alone (Task 2).
- **HA failover during an investigation:** stateless transport means the next call succeeds on the new leader (Task 4).
- **The merge back missing a commit from `main`:** `behind 0` checked right before the merge (Task 8).

---

### Task 1: Implementation security review

- Scope: spec §10.2's list, against the code on `PMM-MCP-GA`, plus the load-test numbers from plan 05 and the node-account evidence from plan 06.
- Every finding is closed or accepted in writing on PMM-15532.

### Task 2: Client and engine matrix

- Claude Code and Cursor against a Feature Build, with a service-account token, on each protocol version go-sdk v1.8.0 negotiates (2024-11-05 to 2026-07-28). For each client, record whether it passes `Instructions` and structured content to the model.
- The triage on MySQL, PostgreSQL and MongoDB; record a tool-by-engine table in `tool-contract.md`.

### Task 3: Failure and agent-behaviour checks

- An agent that is down (`agent_unreachable`), an expired token (`unauthorized`), pmm-managed restarted mid-call.
- The same triage in a loop and three investigations in parallel with different tokens for 10 minutes: `rate_limited` answers, load on the monitored databases and on VictoriaMetrics, every response within its budget. Record on PMM-15532.

### Task 4: HA failover

- On a k3s cluster (`chaos-ha-provisioning` skill): start an investigation, fail the leader over, continue; the next call succeeds.

### Task 5: Telemetry and operator metrics

**Files:** `managed/services/mcp/` (metrics around `addTool`), `managed/services/telemetry/config.default.yml`.
- `mcp_tool_calls_total{tool, code}`, `mcp_tool_duration_seconds{tool}`, `mcp_tool_calls_in_flight{tool}`, exposed on pmm-managed's metrics and scraped by the existing `pmm-managed` job.
- One telemetry item reads 24-hour totals per tool and code through the `VM` data source, plus whether MCP is enabled.
- Tests: counters after a success and after each error code; the telemetry config parses.

### Task 6: Docs and release notes

- `documentation/docs/api/mcp.md` and `documentation/api/welcome/mcp.md` final; release-notes entry: what it is, off by default and how to enable it, Access Roles and service-account tokens (tokens start on the default role), `pmm_advisors` needs Editor.

### Task 7: percona/pmm-mcp

- With the owner's go-ahead: a README pointing to `/mcp`, archive the repository, close its two contributor PRs with thanks and the reason (ADR-01).

### Task 8: Merge back

- Merge `main` into `PMM-MCP-GA`, `make gen`, CI and a Feature Build green, `behind 0`; merge into `main`; delete the branch.
- Regression on a `main` build: the triage with `PMM_ENABLE_MCP=true`, and `POST /mcp` 404 with the default.
- Close or update PMM-15527 to PMM-15532 and PMM-15790 in Jira, with links to the PRs.
