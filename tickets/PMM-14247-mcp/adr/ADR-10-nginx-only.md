# ADR-10: `/mcp` only through nginx, with an Origin check

- Status: Proposed
- Date: 2026-10-22, revised 2026-10-24, 2026-11-02 and 2026-11-06
- Tickets: PMM-14247, PMM-15528, PMM-15532
- Implemented: loopback-peer check in `PMM-MCP-GA` (percona/pmm#5942, #6068); the Origin check and the refusal of anonymous callers not yet (plan 02)

## Context

Authentication of `/mcp` is nginx `auth_request`. nginx proxies to pmm-managed on loopback with the upstream name (`managed-json`) as the `Host` header. The SDK's DNS-rebinding guard rejects a non-loopback `Host` on a loopback connection, so with the guard on, every proxied request failed. The guard also checks only connections that arrive on a loopback address, so it would not stop a direct connection anyway.

A loopback peer shows that a request didn't come from another host. It doesn't prove that the request came through nginx, nor who sent it. The MCP transport specification requires servers to validate `Origin` and to answer 403 to an invalid one. Browsers are held back today only as a side effect: the SDK accepts only `Content-Type: application/json`, which forces a CORS preflight, and nothing on `/mcp` sends CORS headers.

## Options

1. Keep the SDK guard on and rewrite `Host` in nginx. Rejected: the guard checks only connections that arrive on a loopback address, so it still wouldn't stop a direct connection.
2. Keep the SDK guard on, and turn it off only when pmm-managed binds a non-loopback address. Rejected: nginx always connects on loopback, where the guard rejects every proxied request (tried in PMM-15528: 403 on every proxied request); on a non-loopback bind the guard doesn't run, so it adds nothing.
3. Turn the guard off, accept only loopback peers, and check `Origin` explicitly.

For `Origin` and anonymous callers:
- No `Origin` check, relying on the CORS preflight. Rejected: the MCP transport specification requires servers to validate `Origin` [I].
- Refusing requests without an `Authorization` or `Cookie` header in the handler. Rejected: any cookie passes it; only the auth path knows that Grafana resolved the caller as anonymous.

## Decision

Option 3.
- **Loopback only.** `DisableLocalhostProtection: true`. `Handler` answers 404 (the same answer as a disabled endpoint) to any peer that is not a loopback address, and logs the first rejection at warning level. nginx always connects from loopback, so a request from another host can't reach the handler around `auth_request`, whatever interface pmm-managed is bound to. A process on the server itself can connect from loopback too, so the peer check is not what authorizes data: the invariant below is.
- **Origin.** The SDK handler is wrapped in Go's `http.CrossOriginProtection`, which the SDK documentation recommends in place of its own deprecated option. A POST passes when `Sec-Fetch-Site` is `same-origin` or `none`, or when it carries neither that header nor `Origin`, which covers MCP clients that are not browsers. `location /mcp` passes the client's `Host` (`proxy_set_header Host $http_host`), so an `Origin` that names the server's own address passes, and any other `Origin` gets 403.
- **Credentials.** A service token or API key in `Authorization` takes precedence. Otherwise Grafana resolves the user from Basic auth or the session cookie (`getAuthUser` in `managed/services/grafana/client.go`). A backing call that Grafana serves isn't guaranteed to resolve, from the same headers, the principal that `auth_request` resolved for `/mcp`. So MCP forwards the caller's credentials in one canonical form on every backing call (ADR-03; plan 06, before the service list is served by Grafana): when the caller sent a token, `Authorization: Bearer <token>` and no `Cookie`; otherwise Basic `Authorization` and `Cookie` unchanged. Each backing call is authorized again with those headers. MCP never logs either header, at any log level (plan 04). `auth_request` refuses `/mcp` with 403 to a caller that Grafana resolves as anonymous, so a server with Grafana's anonymous access on doesn't serve MCP without credentials.
- **Invariant.** A tool returns only public data, such as `pmm_catalog`'s reference data, unless a backing call authorized it with the caller's headers.

## Consequences

- `/mcp` can't be reached around nginx from another host, even when `PMM_INTERFACE_TO_BIND` makes pmm-managed's port routable.
- A front proxy that connects to pmm-managed other than over loopback makes MCP look switched off.
- A page on another origin can't call `/mcp` from a browser, with or without the user's cookie.
- PMM's node service-account tokens are Admin (ADR-12), so a node's token can use `/mcp` with Admin's role. Accepted: MCP gives a token no capability beyond what it has through the REST API (ADR-03).
- Revoking a token can take up to 60 s to reach MCP, because pmm-managed's auth server caches its answers for that long [V]. Accepted; `mcp.md` says so (plan 04).
- Tests: a cross-site `Origin` gets 403; a request without `Origin` is served; a same-origin browser request is served, and so is a request whose `Origin` is the server's address without `Sec-Fetch-Site`; an anonymous caller gets 403; a non-loopback peer gets 404; a backing call carries a token as `Authorization: Bearer <token>` with no `Cookie`, and Basic credentials and a cookie unchanged.
- All of this is part of the security design review ([spec §10](../spec.md#10-phase-5-release), item 2).
