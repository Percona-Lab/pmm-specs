# ADR-05: Read-only tools

- Status: Proposed
- Date: 2026-10-22, revised 2026-10-24
- Tickets: PMM-14247, PMM-15529
- Implemented: read-only tool set in `PMM-MCP-GA` (percona/pmm#5942); per-caller limit not yet (phase 2)

## Context

The endpoint is driven by language models. A tool that changes state can be triggered by a model's mistake or by instructions injected into data the model reads. A tool that only reads can still cost the monitored database something, and an agent running in a loop can call it many times.

## Options

1. Read-only tools only.
2. Read and write tools, with confirmation left to the client.

## Decision

Option 1. Every tool carries `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` and `openWorldHint: false`. The hints are metadata for clients; what keeps a tool read-only is the backing calls it makes.

Tools are of two kinds:
- **Passive** tools read what PMM has already collected: `pmm_version`, `pmm_inventory`, `pmm_top_queries`, `pmm_query_detail`, `pmm_qan_columns`, `pmm_get_config`, `pmm_query_metrics`, `pmm_list_metrics`, `pmm_alerts`, `pmm_advisors`, and `pmm_get_explain` for PostgreSQL (the stored plan).
- **Live inspection** starts a pmm-agent action on the monitored database: `pmm_get_explain` for MySQL and MongoDB, and `pmm_get_schema`. MySQL EXPLAIN is always the non-executing form, never `EXPLAIN ANALYZE`. MongoDB `explain` is sent without a verbosity, so the server's default applies, which runs the candidate plans to collect statistics [I]; it never modifies data.

Live inspection is bounded:
- pmm-agent runs at most 2 actions at once per database instance and 32 in total, each with a 10 s limit (existing, `agent/runner/runner.go`);
- one MCP call is bounded by `PMM_MCP_ACTION_TIMEOUT` and keeps at most 4 actions in flight;
- new: at most 2 live-inspection calls in flight per caller, keyed by a hash of the caller's credentials; a further call answers `rate_limited` at once. The phase 2 plan may change the number. Metric queries have a limit of their own (ADR-15).

## Consequences

- No tool can change PMM or a monitored database.
- Viewers can already start the same actions from QAN; MCP adds call volume, not a new capability. The per-caller limit bounds that volume.
- `rate_limited` joins the error codes of the contract (ADR-11).
- Who may start live inspection is part of the security review (spec §10.2).
- Write tools, if ever wanted, need a new ADR.
