# ADR-04: Stateless Streamable HTTP

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15528
- Implemented: `PMM-MCP-GA`, percona/pmm#5942

## Context

MCP offers stdio and Streamable HTTP transports. A server can keep a session per client or treat every request on its own. PMM Server runs as one container or as an HA cluster, and restarts during upgrades.

## Options

1. Streamable HTTP with sessions kept in pmm-managed.
2. Streamable HTTP, stateless.
3. A hand-written transport.

## Decision

Option 2, on the official `github.com/modelcontextprotocol/go-sdk` with `Stateless: true`. The SDK's default response mode (SSE) stays unless a client misbehaves behind nginx.

## Consequences

- No session table: nothing to replicate in HA, and restarts are transparent to clients.
- Every request carries its own credentials and is authorized on its own (ADR-03).
- GET and DELETE on `/mcp` answer 405, by SDK design.
- Server-initiated features that need a session (notifications, sampling) are unavailable. The read-only tool surface doesn't need them.
