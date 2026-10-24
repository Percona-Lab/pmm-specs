# ADR-05: Read-only tools

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247
- Implemented: `PMM-MCP-GA`, percona/pmm#5942

## Context

The endpoint is driven by language models. A tool that changes state can be triggered by a model's mistake or by instructions injected into data the model reads.

## Options

1. Read-only tools only.
2. Read and write tools, with confirmation left to the client.

## Decision

Option 1. Every tool carries `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` and `openWorldHint: false`. MySQL EXPLAIN is always the non-executing form, never `EXPLAIN ANALYZE`. MongoDB `explain` runs the read to collect statistics but never modifies data.

## Consequences

- No tool can change PMM or a monitored database.
- Live EXPLAIN and schema actions still run on the monitored database through pmm-agent. They are reads, but they reach the database itself, so who may start them is part of the security review (phase 5).
- Write tools, if ever wanted, need a new ADR.
