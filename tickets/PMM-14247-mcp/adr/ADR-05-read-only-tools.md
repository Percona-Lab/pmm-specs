# ADR-05: Read-only tools

- Status: Proposed
- Date: 2026-10-22, revised 2026-10-24, 2026-10-26, 2026-11-02 and 2026-11-06
- Tickets: PMM-14247, PMM-15529
- Implemented: read-only tool set in `PMM-MCP-GA` (percona/pmm#5942); caps, cancellation and the caller key not yet (plan 02)

## Context

The endpoint is driven by language models. A tool that changes state can be triggered by a model's mistake or by instructions injected into data the model reads. A tool that only reads can still cost the monitored database something, and an agent running in a loop can call it many times.

## Options

1. Read-only tools only.
2. Read and write tools, with confirmation left to the client. Rejected: a model's mistake or an injected instruction could change PMM or a monitored database, and confirmation depends on each client.

For the limits on live inspection:
- No limit beyond pmm-agent's own. Rejected: pmm-agent's limits don't stop one AI client from keeping a database busy.
- Keying the caps by the raw `Authorization` and `Cookie` headers. Rejected: a caller gets a new allowance by adding or reshaping a header.
- A limiter shared across HA replicas. Rejected for this epic: it needs shared state; the per-replica cap bounds each replica.

## Decision

Option 1. Every tool carries `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` and `openWorldHint: false`. The hints are metadata for clients; what keeps a tool read-only is the backing calls it makes.

Tools are of two kinds:
- **Passive** tools read what PMM has already collected: `pmm_version`, `pmm_inventory`, `pmm_top_queries`, `pmm_query_detail`, `pmm_catalog`, `pmm_get_config`, `pmm_service_health`, `pmm_query_metrics`, `pmm_list_metrics`, `pmm_alerts`, and `pmm_get_explain` for PostgreSQL (the stored plan).
- **Live inspection** starts a pmm-agent action on the monitored database: `pmm_get_explain` for MySQL and MongoDB, and `pmm_get_schema`. MySQL EXPLAIN is always the non-executing form, never `EXPLAIN ANALYZE`. MongoDB `explain` is sent without a verbosity, so the server's default applies, which runs the candidate plans to collect statistics [I]; it never modifies data. It runs on the example QAN stored for the resolved service (spec §6.1); the free-form `query` input is removed once resolve-first lands, so a model can't have an arbitrary statement run. `queryPlanner` verbosity, which doesn't execute, needs a pmm-agent change and is left out of this epic.

Live inspection is bounded (values in [spec §8](../spec.md#8-phase-3-output-contract)):
- pmm-agent stops each action after 10 s (existing, `agent/runner/runner.go`);
- one MCP call is bounded by `PMM_MCP_ACTION_TIMEOUT` and keeps at most 4 actions in flight;
- new: a cap on live-inspection calls in flight per caller and per pmm-managed replica across all callers, and one live call per service on each replica, whoever the callers are (plan 04); a further call answers `rate_limited` at once. MCP doesn't rely on pmm-agent's own concurrency limits. Metric queries have caps of their own (ADR-15).
- new: a token bucket per caller limits how often live-inspection calls start (plan 05); an empty bucket answers `rate_limited` with `retry_after` (ADR-11).
- new: when an MCP call times out, its client disconnects, or it ends while some of its actions still run, it cancels each unfinished action with `POST /v1/actions:cancelAction`. pmm-agent registers the cancel before an action waits for a slot (`agent/runner/runner.go:349-350`) [V], so this also clears queued work: when a call ends, none of its actions stays queued or running on pmm-agent. In Stateless mode an MCP `notifications/cancelled` message doesn't reach the running handler [V, go-sdk v1.8.0], so only a disconnect or the timeout cancels.
- **The caller** is the service-account token when the request carries one, else the Basic-auth user name, else the PMM session cookie (`pmm_session`), identified by a hash; the raw headers are never the key, so adding or reshaping a header doesn't buy a new allowance. The per-caller cap is therefore **per token, user or session, per replica**: a service account with several tokens gets one allowance per token, and an HA cluster one per replica. The per-replica caps and the per-service cap bound the total. Keying by the principal would need the caller's identity inside MCP, which this epic doesn't pass (spec §9.1); there is no distributed limiter.

## Consequences

- No tool can change PMM or a monitored database.
- Live inspection needs the same Grafana role as EXPLAIN in QAN's UI; MCP adds call volume, not a new capability, and starts actions only on services in the caller's list (ADR-03). The caps bound that volume.
- `rate_limited` joins the error codes of the contract (ADR-11).
- Who may start live inspection is part of the security review ([spec §10](../spec.md#10-phase-5-release), item 2).
- Write tools, if ever wanted, need a new ADR.
