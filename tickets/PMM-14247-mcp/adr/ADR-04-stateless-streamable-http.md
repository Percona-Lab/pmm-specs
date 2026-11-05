# ADR-04: Stateless Streamable HTTP

- Status: Accepted (2026-11-05), after the review in pmm-specs#4
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15528
- Implemented: `PMM-MCP-GA`, percona/pmm#5942

## Context

MCP offers stdio and Streamable HTTP transports. A server can keep a session per client or treat every request on its own. PMM Server runs as one container or as an HA cluster, and restarts during upgrades.

## Options

1. Streamable HTTP with sessions kept in pmm-managed. Rejected: session state to replicate across HA replicas, for no tool that needs it.
2. Streamable HTTP, stateless.
3. A hand-written transport. Rejected: protocol work the official SDK already does and tracks.

## Decision

Option 2, on the official `github.com/modelcontextprotocol/go-sdk` with `Stateless: true`. The SDK's default response mode (SSE) stays unless a client fails to receive streamed responses through nginx.

## Consequences

- No session table, so nothing to replicate in HA. A restart fails only the calls in flight; clients don't re-initialize a session. Failover is untested (spec §11).
- Every request carries its own credentials and is authorized on its own (ADR-03).
- GET and DELETE on `/mcp` answer 405, by SDK design.
- Server-initiated features that need a session (notifications, sampling) are unavailable. The read-only tool surface doesn't need them.
