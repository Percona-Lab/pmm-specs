# ADR-10: `/mcp` only through nginx, with an Origin check

- Status: Proposed
- Date: 2026-10-22, revised 2026-10-24
- Tickets: PMM-14247, PMM-15528, PMM-15532
- Implemented: loopback-peer check in `PMM-MCP-GA` (percona/pmm#5942, #6068); Origin check not yet

## Context

Authentication of `/mcp` is nginx `auth_request`. nginx proxies to pmm-managed on loopback with the upstream name (`managed-json`) as the `Host` header. The SDK's DNS-rebinding guard rejects a non-loopback `Host` on a loopback connection, so with the guard on, every proxied request failed. The guard also checks only connections that arrive on a loopback address, so it would not stop a direct connection anyway.

A loopback peer proves that a request came through nginx, not who sent it to nginx. The MCP transport specification requires servers to validate `Origin` and to answer 403 to an invalid one. Browsers are held back today only as a side effect: the SDK accepts only `Content-Type: application/json`, which forces a CORS preflight, and nothing on `/mcp` sends CORS headers.

## Options

1. Keep the SDK guard on and rewrite `Host` in nginx.
2. Keep the guard only for non-loopback binds.
3. Turn the guard off, accept only loopback peers, and check `Origin` explicitly.

## Decision

Option 3.
- **Loopback only.** `DisableLocalhostProtection: true`. `Handler` answers 404 (the same answer as a disabled endpoint) to any peer that is not a loopback address, and logs the first rejection at warning level. nginx always connects from loopback, so every accepted request came through `auth_request`, whatever interface pmm-managed is bound to. Option 2 was tried in PMM-15528 and turned every proxied request into a 403.
- **Origin.** The SDK handler is wrapped in Go's `http.CrossOriginProtection`, which the SDK documentation recommends in place of its own deprecated option. A POST passes when `Sec-Fetch-Site` is `same-origin` or `none`, or when it carries neither that header nor `Origin`, which covers MCP clients that are not browsers. Any other `Origin` gets 403, because it can't match the `Host` that nginx sends [I].
- **Credentials.** A service token or API key in `Authorization` takes precedence. Otherwise Grafana resolves the user from Basic auth or the session cookie (`getAuthUser` in `managed/services/grafana/client.go`). MCP copies `Authorization` and `Cookie` unchanged onto every backing call (ADR-03), so each backing call resolves the same principal as the `/mcp` request. Neither header is ever logged.

## Consequences

- `/mcp` can't be reached around nginx, even when `PMM_INTERFACE_TO_BIND` makes pmm-managed's port routable.
- A front proxy that connects to pmm-managed other than over loopback makes MCP look switched off.
- A page on another origin can't call `/mcp` from a browser, with or without the user's cookie.
- Tests: a cross-site `Origin` gets 403; a request without `Origin` is served; a same-origin browser request is served; a non-loopback peer gets 404; a backing call carries the caller's headers unchanged.
- All of this is part of the security design review (spec §10.2).
