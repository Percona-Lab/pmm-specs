# ADR-10: `/mcp` only through nginx, with an Origin check

- Status: Proposed
- Date: 2026-10-22, revised 2026-10-24 and 2026-11-02
- Tickets: PMM-14247, PMM-15528, PMM-15532
- Implemented: loopback-peer check in `PMM-MCP-GA` (percona/pmm#5942, #6068); the Origin check and the refusal of anonymous callers not yet (plan 02)

## Context

Authentication of `/mcp` is nginx `auth_request`. nginx proxies to pmm-managed on loopback with the upstream name (`managed-json`) as the `Host` header. The SDK's DNS-rebinding guard rejects a non-loopback `Host` on a loopback connection, so with the guard on, every proxied request failed. The guard also checks only connections that arrive on a loopback address, so it would not stop a direct connection anyway.

A loopback peer proves that a request came through nginx, not who sent it to nginx. The MCP transport specification requires servers to validate `Origin` and to answer 403 to an invalid one. Browsers are held back today only as a side effect: the SDK accepts only `Content-Type: application/json`, which forces a CORS preflight, and nothing on `/mcp` sends CORS headers.

## Options

1. Keep the SDK guard on and rewrite `Host` in nginx. Rejected: the guard checks only connections that arrive on a loopback address, so it still wouldn't stop a direct connection.
2. Keep the SDK guard on, and turn it off only when pmm-managed binds a non-loopback address. Rejected: nginx always connects on loopback, where the guard rejects every proxied request (tried in PMM-15528: 403 on every proxied request); on a non-loopback bind the guard doesn't run, so it adds nothing.
3. Turn the guard off, accept only loopback peers, and check `Origin` explicitly.

For `Origin` and anonymous callers:
- No `Origin` check, relying on the CORS preflight. Rejected: the MCP transport specification requires servers to validate `Origin` [I].
- Refusing requests without an `Authorization` or `Cookie` header in the handler. Rejected: any cookie passes it; only the auth path knows that Grafana resolved the caller as anonymous.

## Decision

Option 3.
- **Loopback only.** `DisableLocalhostProtection: true`. `Handler` answers 404 (the same answer as a disabled endpoint) to any peer that is not a loopback address, and logs the first rejection at warning level. nginx always connects from loopback, so every accepted request came through `auth_request`, whatever interface pmm-managed is bound to.
- **Origin.** The SDK handler is wrapped in Go's `http.CrossOriginProtection`, which the SDK documentation recommends in place of its own deprecated option. A POST passes when `Sec-Fetch-Site` is `same-origin` or `none`, or when it carries neither that header nor `Origin`, which covers MCP clients that are not browsers. `location /mcp` passes the client's `Host` (`proxy_set_header Host $http_host`), so an `Origin` that names the server's own address passes, and any other `Origin` gets 403.
- **Credentials.** A service token or API key in `Authorization` takes precedence. Otherwise Grafana resolves the user from Basic auth or the session cookie (`getAuthUser` in `managed/services/grafana/client.go`). MCP copies `Authorization` and `Cookie` unchanged onto every backing call (ADR-03), so each backing call resolves the same principal as the `/mcp` request. MCP never logs either header. `auth_request` refuses `/mcp` with 403 to a caller that Grafana resolves as anonymous, so a server with Grafana's anonymous access on doesn't serve MCP without credentials.

## Consequences

- `/mcp` can't be reached around nginx, even when `PMM_INTERFACE_TO_BIND` makes pmm-managed's port routable.
- A front proxy that connects to pmm-managed other than over loopback makes MCP look switched off.
- A page on another origin can't call `/mcp` from a browser, with or without the user's cookie.
- Tests: a cross-site `Origin` gets 403; a request without `Origin` is served; a same-origin browser request is served, and so is a request whose `Origin` is the server's address without `Sec-Fetch-Site`; an anonymous caller gets 403; a non-loopback peer gets 404; a backing call carries the caller's headers unchanged.
- All of this is part of the security design review ([spec §10](../spec.md#10-phase-5-release), item 2).
