# ADR-11: Output contract

- Status: Proposed
- Date: 2026-10-22, revised 2026-10-24
- Tickets: PMM-14247, PMM-15530
- Implemented: not yet (phase 3; the contract is written before the rest of phase 2)

## Context

The tools return prose with "View in PMM" links. That suits a person driving Claude Code or Cursor. A program needs compact, typed, bounded results, and needs to tell errors apart without parsing prose. `pmm_inventory` has no cap and returns every service at once. Tool descriptions sit in the model's context on every turn, and the QAN column catalogue makes `pmm_top_queries`' description large. Phase 2 is adding inputs and results now; fixing the contract after it would mean reworking them. The endpoint is unreleased, so the contract can still change without breaking anyone.

## Options

1. Text only, as today.
2. A separate set of structured tools beside the text tools.
3. Every tool returns both, from one result value.

## Decision

Option 3.
- Each tool has a Go output type. The handler builds the value once. The Go SDK (v1.8.0) infers `outputSchema` from the type, validates the value and sends it as `structuredContent`. The text is rendered from the same value.
- Redaction (ADR-07) runs on the value, before either rendering.
- Every listing tool takes `limit` and `offset` and reports `total`, `offset`, `limit` and `truncated`; the text ends with an explicit truncation marker. Starting caps are in [spec §8](../spec.md#8-phase-3-output-contract).
- The error codes are part of the contract: the eight in `errors.go` plus `rate_limited` (ADR-05). An error stays an `isError` result. Its text starts with `error: <code>` for the model, and its `_meta` carries `percona.com/error: {code, retryable}` for programs. `timeout`, `agent_unreachable`, `pmm_unavailable` and `rate_limited` are retryable; the others are not.
- The QAN column catalogue moves to a new read-only tool, `pmm_qan_columns`.
- The contract is written in `tool-contract.md` in this folder and reviewed before the rest of phase 2 is built. For each tool it lists the inputs, outputs, error codes and caps, the minimum Grafana role, the backing APIs, whether LBAC filters the data, whether the tool is passive or live (ADR-05), and the engines it supports. A golden-file test in percona/pmm snapshots `tools/list`.
- Until release the contract may change freely; afterwards, only additively.

## Consequences

- Human clients keep prose and links; programs get typed data and typed errors; both come from one implementation.
- Responses roughly double in size, because structured content repeats the text's data. Caps and the token measurement on PMM-15530 must account for it.
- Any change to a tool's inputs or outputs shows up as a golden-file diff in review.
- One more tool in `tools/list`, in exchange for a shorter `pmm_top_queries` description.
- The remaining phase 2 work waits for the contract review.
