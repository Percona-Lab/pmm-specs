# ADR-10: `/mcp` served only through nginx

- Status: Proposed
- Date: 2026-10-22
- Tickets: PMM-14247, PMM-15528, PMM-15532
- Implemented: `PMM-MCP-GA`, percona/pmm#5942 and #6068

## Context

Authentication of `/mcp` is nginx `auth_request`. nginx proxies to pmm-managed on loopback with the upstream name (`managed-json`) as the `Host` header. The SDK's DNS-rebinding guard rejects a non-loopback `Host` on a loopback connection, so with the guard on, every proxied request failed. The guard also checks only connections that arrive on a loopback address, so it would not stop a direct connection anyway.

## Options

1. Keep the SDK guard on and rewrite `Host` in nginx.
2. Keep the guard only for non-loopback binds.
3. Turn the guard off and accept only loopback peers.

## Decision

Option 3. `DisableLocalhostProtection: true`. `Handler` answers 404 (the same answer as a disabled endpoint) to any peer that is not a loopback address, and logs the first rejection at warning level. nginx always connects from loopback, so every accepted request came through `auth_request`, whatever interface pmm-managed is bound to. Option 2 was tried in PMM-15528 and turned every proxied request into a 403.

## Consequences

- `/mcp` can't be reached around nginx, even when `PMM_INTERFACE_TO_BIND` makes pmm-managed's port routable.
- A front proxy that connects to pmm-managed other than over loopback makes MCP look switched off.
- The check is part of the phase 5 security review.
