# Origin check, credentials and live-inspection limits Implementation Plan

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans).

**Goal:** Refuse cross-site browser requests and anonymous callers to `/mcp` (ADR-10); bound the live-inspection calls one caller and one replica can have in flight, and cancel the pmm-agent actions a call leaves behind (ADR-05).

**Architecture:** `auth_request` refuses `/mcp` to a caller that Grafana resolves as anonymous (403). `Handler` then checks, in order: loopback peer (404), the enabled switch (404), Go's `http.CrossOriginProtection` (403), then the SDK handler. A small in-memory `limiter` counts calls in flight per caller key and per replica; plan 05 reuses it for metric calls. `runAction` cancels its action on every path that leaves it unfinished.

**Tech Stack:** Go 1.27 `net/http` (`CrossOriginProtection`, Go 1.25+), go-sdk v1.8.0, nginx, PMM's auth server (`managed/services/grafana`).

**Spec:** [ADR-10](../adr/ADR-10-nginx-only.md), [ADR-05](../adr/ADR-05-read-only-tools.md), [spec §6.6, §11](../spec.md#66-acceptance).

## Global Constraints

- Two tickets, two branches, two PRs into `PMM-MCP-GA` ([00](00-roadmap.md#branch-and-pr-rules)): Tasks 1 and 2 on `PMM-15528-origin-and-credentials`, Tasks 3 and 4 on `PMM-15529-live-inspection-limits`. Both are cut from `PMM-MCP-GA` after plan 01 and don't depend on each other.
- A disabled endpoint stays invisible to every caller that passes `auth_request`: 404 before the Origin check, whatever the request carries.
- `auth_request` refuses `/mcp` with 403 to a caller that Grafana resolves as anonymous, also one that sends a cookie that is not a session (ADR-10). Other paths are unchanged for anonymous callers.
- Live inspection: at most 2 calls in flight per caller and 8 per replica ([spec §8](../spec.md#8-phase-3-output-contract)); the next call answers `rate_limited` at once, never waits.
- **Caller** and **replica** as in [00](00-roadmap.md#terms). The caller key is a SHA-256 hash of the service-account token when the request carries one (`auth.GetTokenFromHeaders`, `managed/utils/auth/token.go:33-52`), else of the user name of Basic credentials, else of the Grafana session cookie (`pmm_session`, `login_cookie_name` in `build/ansible/roles/grafana/files/grafana.ini:75`). A request with none of the three shares one key with all such requests.
- The key is never the raw `Authorization` and `Cookie` headers, so an extra cookie or another token form gets no new allowance. No credential is logged or stored in clear.
- A call that times out, is cancelled, or ends with some of its actions still running cancels each unfinished action it started with `POST /v1/actions:cancelAction`, and holds its slot until then. Actions that finished are not cancelled.
- In `Stateless` mode an MCP `notifications/cancelled` never reaches the handler: each request gets its own temporary session (go-sdk v1.8.0 `mcp/streamable.go:367-369`). Only the call's timeout, or an HTTP disconnect with `PropagateRequestCancellation` (protocol 2026-07-28 and later), cancels a call.
- PostgreSQL's stored plan is passive (ADR-05) and not limited.
- No named results in non-test code (`nonamedreturns` is on in `.golangci.yml`).

## Review Focus

- **An MCP client that sends no `Origin` and no `Sec-Fetch-Site`** (Claude Code, Cursor, curl) must keep working, and so must a client that sends `Origin` equal to the public host: Task 1 step 1 tests both.
- **A failed or cancelled live call must release its slot,** or a caller locks itself out: Task 3 step 2 tests release on error and on context cancellation.
- **One caller at its limit must not block another caller:** Task 3 step 1 tests two keys.
- **An abandoned call must not leave work queued on pmm-agent:** Task 4 step 1 tests that each unfinished action is cancelled, and only those.

---

### Task 1: Origin check (ADR-10)

**Files:**
- Modify: `managed/services/mcp/mcp.go` (`New`, where `s.handler` is built), `build/ansible/roles/nginx/files/conf.d/pmm.conf` (`location /mcp`, `:338-345`)
- Test: `managed/services/mcp/hardening_test.go`

- [ ] **Step 1: Write the failing test `TestOriginCheck`**

Table over raw `POST /mcp` requests to `httptest.NewServer(s.Handler())` (a loopback peer), body `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}`, headers `Content-Type: application/json`, `Accept: application/json, text/event-stream` and `Authorization: <testToken>`. `Host` is the request's `req.Host`; nginx sets it from the browser's `Host` after step 3.

| Case | Host and extra headers | Enabled | Want status |
|---|---|---|---|
| no browser headers | — | yes | 200 |
| same-origin fetch | `Sec-Fetch-Site: same-origin` | yes | 200 |
| Origin = public host, no `Sec-Fetch-Site` | Host `pmm.example`, `Origin: https://pmm.example` | yes | 200 |
| Origin = public host, Host rewritten to the upstream | Host `managed-json`, `Origin: https://pmm.example` | yes | 403 |
| cross-site fetch | `Sec-Fetch-Site: cross-site`, `Origin: https://evil.example` | yes | 403 |
| foreign Origin only | `Origin: https://evil.example` | yes | 403 |
| cross-site, disabled | `Sec-Fetch-Site: cross-site` | no | 404 |

The `managed-json` row shows why nginx must pass the public `Host`: Go's check compares `Origin` with `req.Host` when `Sec-Fetch-Site` is absent.

- [ ] **Step 2: Run it to see the 403 rows fail**

Run: `go test ./managed/services/mcp/ -run TestOriginCheck -v`
Expected: FAIL on the three 403 rows (got 200).

- [ ] **Step 3: Wrap the SDK handler in `New`, and pass the public `Host` in nginx**
  - `New`: `s.handler = http.NewCrossOriginProtection().Handler(mcp.NewStreamableHTTPHandler(...))`. `Handler()` is unchanged, so the loopback and enabled checks still run first.
  - `pmm.conf`, `location /mcp`: add `proxy_set_header Host $http_host;`, as `pmm.conf:200` and `:210` already do for other locations.
  - Update the comment above `DisableLocalhostProtection`: nginx now sends the public `Host` over a loopback connection, which the SDK's DNS-rebinding guard would refuse.
  - `TestServesRequestsProxiedByNginx`: its stand-in for nginx keeps the incoming `Host` (`r.Out.Host = r.In.Host`) instead of `managed-json`, as `pmm.conf` now does.

- [ ] **Step 4: Run the test and the package**

Run: `go test ./managed/services/mcp/...`
Expected: PASS, including `TestHandlerOnlyServesLoopbackPeers`, `TestServesRequestsProxiedByNginx`, `TestDisabled`.

- [ ] **Step 5: Commit** `PMM-15528 Refuse cross-site requests to /mcp`.

### Task 2: Refuse `/mcp` to anonymous callers (ADR-10)

**Files:**
- Modify: `managed/services/grafana/client.go` (`authUser`, `getAuthUser`), `managed/services/grafana/auth_server.go` (`authenticate`), `documentation/docs/api/mcp.md` (`### Errors`)
- Test: `managed/services/grafana/client_test.go` (`TestGetAuthUserAnonymousFallback`), `managed/services/grafana/auth_server_test.go`

**Interfaces:**
- Produces:
  - `authUser` gains `anonymous bool`. `getAuthUser` sets it only in the branch that falls back to Grafana's anonymous role (`client.go:320-327` on `PMM-MCP-GA`). The auth cache keeps it with the rest of `authUser`.
  - `authenticate`: when the matched rule prefix is `/mcp` and `user.anonymous` is set, it returns `&authError{code: codes.PermissionDenied, message: "Access denied"}` before the role checks, so `auth_request` answers 403 (`httpStatusForAuthError`). Every other path is unchanged for anonymous callers.
- `/mcp`'s own handler gets no credentials check: every request it serves came through `auth_request`.

- [ ] **Step 1: Write the failing tests**
  - `TestGetAuthUserAnonymousFallback`: the subtests that fall back to the anonymous role, cookie-only included, return `anonymous: true`; a request whose `/api/user` call succeeds returns `anonymous: false`.
  - `TestAnonymousCallerOnMCP` in `auth_server_test.go`, with a fake Grafana as in `client_test.go` (`/api/user` answers 401, `/api/frontend/settings` answers `{"anonymousEnabled":true,"anonymousOrgRole":"Viewer"}`) and an `AuthServer` on it. `s.authenticate` for a request without credentials, and for one with only `Cookie: junk=1`:
    - `/mcp` and `/mcp/`: `PermissionDenied`;
    - `/v1/server/version` (a Viewer path): `nil`, as before this plan.
  - The same test for a Viewer, with `/api/user` answering `{"id":5}` and `/api/user/orgs` answering `[{"orgId":1,"role":"Viewer"}]` (`getAuthUser` reads the role from there): `/mcp` gives `nil`.

- [ ] **Step 2: Run them to see them fail**

Run: `go test ./managed/services/grafana/ -run 'TestGetAuthUserAnonymousFallback|TestAnonymousCallerOnMCP' -v`
Expected: FAIL to compile (`anonymous` undefined).

- [ ] **Step 3: Implement the field and the refusal.**

- [ ] **Step 4: Run the new tests and the MCP package**

Run: `go test ./managed/services/grafana/ -run 'TestGetAuthUserAnonymousFallback|TestAnonymousCallerOnMCP|TestResolveRule' -v && go test ./managed/services/mcp/...`
Expected: PASS. Not the whole `grafana` package: several of its tests, `TestAuthServerAuthenticate` among them, dial a live Grafana at `127.0.0.1:3000`; CI runs them.

- [ ] **Step 5: Document it** in `### Errors` of `documentation/docs/api/mcp.md`, after the sentence on HTTP 401: "When Grafana's anonymous access is on, PMM refuses `/mcp` to an anonymous caller with HTTP 403."

- [ ] **Step 6: Commit** `PMM-15528 Refuse /mcp to anonymous callers`.

- [ ] **Step 7: Open the PMM-15528 PR**
  - Merge `origin/PMM-MCP-GA` into `PMM-15528-origin-and-credentials`, with `PMM-MCP-GA` behind 0 ([00](00-roadmap.md#branch-and-pr-rules)).
  - Push the branch and run a Feature Build of it. Against it, with `PMM` the host (and port) the browser uses and `TOKEN` a Viewer service-account token:

    ```bash
    B='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}'
    post() { curl -sk -o /dev/null -w '%{http_code}\n' -X POST "https://$PMM/mcp" -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' "$@" -d "$B"; }
    post -H "Authorization: Bearer $TOKEN" -H 'Origin: https://evil.example' -H 'Sec-Fetch-Site: cross-site'   # 403
    post -H "Authorization: Bearer $TOKEN" -H "Origin: https://$PMM"                                           # 200
    post -H "Authorization: Bearer $TOKEN"                                                                     # 200
    ```

  - Restart the container with `-e GF_AUTH_ANONYMOUS_ENABLED=true`. Then `post` without credentials answers 403, `post -H 'Cookie: junk=1'` answers 403, and `curl -sk -o /dev/null -w '%{http_code}\n' "https://$PMM/v1/server/version"` without credentials answers as before this plan. Claude Code connected with the token still completes the triage ([00](00-roadmap.md#verification-before-each-pr)).
  - Open the PR `PMM-15528 Refuse cross-site and anonymous requests to /mcp` into `PMM-MCP-GA`, with the Feature Build link.

### Task 3: Live-inspection limits (ADR-05)

**Files:**
- Create: `managed/services/mcp/limits.go`, `managed/services/mcp/limits_test.go`
- Modify: `managed/services/mcp/errors.go` (new code), `mcp.go` (`Service.live`, set in `New`), `tools_actions.go` (`explain`, `schema`), `documentation/docs/api/mcp.md` (`### Errors`)
- Test: `managed/services/mcp/tools_actions_test.go`

**Interfaces:**
- Produces:
  - `type limitHit int` with `limitNone`, `limitPerCaller` and `limitPerReplica`.
  - `type limiter struct` (a mutex, the two caps, the total in flight and `byKey map[string]int`) with `func newLimiter(perCaller, total int) *limiter` and `func (l *limiter) acquire(key string) (func(), limitHit)`. It returns `limitNone` and a release function when the call may start, else `nil` and the cap that refused it; the per-caller cap is checked first. The release function is idempotent and deletes `key` from `byKey` when its count reaches 0, so the map holds only callers with calls in flight.
  - `func callerKey(a callerAuth) string`: hex SHA-256 of `"token\x00" + <token>` when `auth.GetTokenFromHeaders` finds one in `a.authorization`, else of `"user\x00" + <user name>` when `a.authorization` holds Basic credentials (`(*http.Request).BasicAuth`), else of `"session\x00" + <value of the pmm_session cookie>` from `a.cookie`, else of `""`.
  - `codeRateLimited errorCode = "rate_limited"` in `errors.go`.
  - `const maxLiveCallsPerCaller = 2`, `maxLiveCallsPerReplica = 8` in `limits.go`; `New` sets `s.live = newLimiter(maxLiveCallsPerCaller, maxLiveCallsPerReplica)`.
  - `func (s *Service) startLive(a callerAuth) (func(), error)`: on `limitPerCaller` or `limitPerReplica`, the error is a `*toolError` with `codeRateLimited` and that cap's message. Per caller: "at most 2 live-inspection calls can be in flight for these credentials; retry when one finishes". Per replica: "this replica already has 8 live-inspection calls in flight; retry when one finishes".
- Plan 05 reuses `limiter`, `callerKey` and `codeRateLimited`.

- [ ] **Step 1: Write `TestLimiter` and `TestCallerKey` in `limits_test.go`**

```go
l := newLimiter(2, 3)
relA1, hit1 := l.acquire("a")
relA2, hit2 := l.acquire("a")
_, hit3 := l.acquire("a")
require.Equal(t, limitNone, hit1); require.Equal(t, limitNone, hit2)
require.Equal(t, limitPerCaller, hit3)
relB, hitB := l.acquire("b")
_, hitC := l.acquire("c")
require.Equal(t, limitNone, hitB); require.Equal(t, limitPerReplica, hitC)
_, hitA := l.acquire("a") // both caps full: the per-caller cap is reported
require.Equal(t, limitPerCaller, hitA)
relA1(); relA1() // idempotent
relA3, hitA3 := l.acquire("a")
require.Equal(t, limitNone, hitA3)
relA2(); relA3(); relB()
require.Empty(t, l.byKey) // keys at 0 are deleted
```

`TestCallerKey`, over `callerAuth` values:
- `Bearer T` and `Basic base64("service_token:T")` give the same key;
- `Bearer T` with no cookie, with `Cookie: x=1` and with `Cookie: pmm_session=s` give the same key;
- `Bearer T1` and `Bearer T2` differ;
- Basic `alice:pw` with and without a cookie give the same key; Basic `alice:pw` and `bob:pw` differ;
- `Cookie: pmm_session=s1` and `Cookie: pmm_session=s2` differ; `pmm_session=s1` with and without `other=1` give the same key;
- no key contains the token, the user name or the cookie value.

- [ ] **Step 2: Write `TestLiveInspectionRateLimited` in `tools_actions_test.go`**

With the fixtures `TestSchemaTool` and `TestExplainTool` use, and `key := callerKey(callerAuth{authorization: testToken})`:
1. Take both of `key`'s slots on `s.live`. `pmm_get_schema`: text starts `error: rate_limited` and names "these credentials", `isError` true, and the fake PMM recorded no `POST /v1/actions:startServiceAction`.
2. Still at 2: `pmm_get_explain` on the PostgreSQL fixture (stored plan) succeeds.
3. Release one slot: `pmm_get_schema` succeeds. Release the other.
4. Take 8 slots with the keys `other-0` to `other-7`, each `limitNone`. `pmm_get_explain` on the MySQL fixture: `error: rate_limited`, naming "this replica". Release the 8.
5. After a `pmm_get_schema` that fails (an action fixture with an error), `s.live.acquire(key)` succeeds twice. Release both.
6. With `newActionStub(t, 0, "ddl-customers")`, whose DDL action never finishes, call `s.schema` directly, not through the session: `ctx, cancel := context.WithCancel(t.Context())`, `&mcp.CallToolRequest{Extra: &mcp.RequestExtra{Header: http.Header{"Authorization": {testToken}}}}`, `schemaInput{ServiceID: "svc-1", Database: "shop", Tables: []string{"customers"}}`. Call `cancel()` once the stub recorded the start. The call returns, and `s.live.acquire(key)` succeeds twice. The test calls the handler directly because nothing a client sends through a session cancels a call mid-poll: in `Stateless` mode a `notifications/cancelled` never reaches the handler (`mcp/streamable.go:367-369`), and a disconnect cancels only with `PropagateRequestCancellation` on protocol 2026-07-28 and later (`mcp/streamable.go:210-219`).

- [ ] **Step 3: Run them to see them fail**

Run: `go test ./managed/services/mcp/ -run 'TestLimiter|TestCallerKey|TestLiveInspectionRateLimited' -v`
Expected: FAIL to compile (`newLimiter` undefined).

- [ ] **Step 4: Implement `limits.go`, the error code and `startLive`; call `startLive` in `schema` before `tableInfo`, and in `explain` on the MySQL and MongoDB paths before `runAction`, with `defer release()`.**

- [ ] **Step 5: Run the package tests**

Run: `go test -race ./managed/services/mcp/...`
Expected: PASS.

- [ ] **Step 6: Document `rate_limited`** in `### Errors` of `documentation/docs/api/mcp.md`: add it to the list of codes, and add: "`rate_limited`: too many live-inspection calls are in flight for these credentials (2) or on this replica (8). Retry when one finishes."

- [ ] **Step 7: Commit** `PMM-15529 Limit live inspection per caller and replica`.

### Task 4: Cancel the actions a call leaves behind (ADR-05)

**Files:**
- Modify: `managed/services/mcp/deps.go` (`pmmAPI`), `client.go`, `mock_pmm_api_test.go` (regenerated), `tools_actions.go` (`runAction`), `mcp.go` (`New`), `documentation/docs/api/mcp.md` (`PMM_MCP_ACTION_TIMEOUT` row)
- Test: `managed/services/mcp/tools_actions_test.go` (`newActionStub`, `TestActionDeadlineIsPerCall`, `TestLiveInspectionRateLimited`)

**Interfaces:**
- Produces:
  - `pmmAPI.CancelAction(ctx context.Context, auth callerAuth, actionID string) error`: `POST /v1/actions:cancelAction` through the generated `actions_service` client, with the caller's credentials. Viewers may call it (`"/v1/actions:"` is `viewer`, `auth_server.go:88`).
  - `const cancelTimeout = 5 * time.Second`.
  - `runAction`: once `StartServiceAction` has returned an action ID, every return before the action is `Done` (the context ended, or `GetAction` failed) first calls `CancelAction` with `context.WithTimeout(context.WithoutCancel(ctx), cancelTimeout)`. A failed cancel is logged at warning level with the action ID, and the call's own error is returned unchanged. The caller's `defer release()` runs after `runAction` returns, so the slot is held until the cancel was sent.
  - `New` sets `PropagateRequestCancellation: true` in `StreamableHTTPOptions`, so an AI client that disconnects (protocol 2026-07-28 and later) cancels its call and, through `runAction`, its unfinished actions. On older protocol versions, and for a `notifications/cancelled`, which never reaches the handler in `Stateless` mode, the call runs to `PMM_MCP_ACTION_TIMEOUT` and then cancels them.
- pmm-agent registers the cancel before an action waits for a slot (`agent/runner/runner.go:349-350`), so a cancel also clears queued work.

- [ ] **Step 1: Write the failing tests**
  - `newActionStub` answers `POST /v1/actions:cancelAction` with `{}` and records each `action_id` and the request's `Authorization`.
  - `TestActionDeadlineIsPerCall` (DDL finishes, `index-customers` never does): the stub recorded exactly one cancel, for `index-customers`, none for the DDL action, with `testToken` as `Authorization`.
  - `TestLiveInspectionRateLimited`, item 6 of Task 3 step 2: the stub recorded one cancel, for the action that was polled when the context was cancelled.
  - `TestSchemaManyTables`:
    - `SlowTableTimesOutAlone`: exactly one cancel, for `ddl-slow`; none for `ddl-a` and `ddl-b`, which finish;
    - `EveryActionFails`: one cancel each for `ddl-x` and `ddl-y`;
    - `Concurrent`, `AtMostFourInFlight` and `InfoTypes`, where every action finishes: no cancel.

- [ ] **Step 2: Run them to see them fail**

Run: `go test ./managed/services/mcp/ -run 'TestActionDeadlineIsPerCall|TestLiveInspectionRateLimited|TestSchemaManyTables' -v`
Expected: FAIL (no cancel recorded).

- [ ] **Step 3: Implement `CancelAction` and the cancel in `runAction`; set `PropagateRequestCancellation`; regenerate the mock** with `go tool mockery --config .mockery.yaml` from the repository root, and commit only `managed/services/mcp/mock_pmm_api_test.go`.

- [ ] **Step 4: Run the package tests**

Run: `go test -race ./managed/services/mcp/...`
Expected: PASS.

- [ ] **Step 5: Update the `PMM_MCP_ACTION_TIMEOUT` row** of `documentation/docs/api/mcp.md`: "Actions still running then are cancelled on pmm-agent and end with a `timeout` error."

- [ ] **Step 6: Commit** `PMM-15529 Cancel unfinished actions of an MCP call`.

- [ ] **Step 7: Open the PMM-15529 PR**
  - Merge `origin/PMM-MCP-GA` into `PMM-15529-live-inspection-limits`, with `PMM-MCP-GA` behind 0.
  - Push the branch and run a Feature Build of it, with the container started with `-e PMM_MCP_ACTION_TIMEOUT=5s`. In a MySQL session, hold `LOCK TABLES <t> WRITE`, which makes `EXPLAIN` of a query on `<t>` wait for its metadata lock. Then, with one Viewer token:
    - `pmm_get_explain` for the `queryid` of a query on `<t>` answers `timeout` after about 5 s, and pmm-agent's log shows `Action finished.` for that action with a duration of about 5 s, not 10 s;
    - three such calls at once: the third answers `rate_limited` at once.
  - Open the PR `PMM-15529 Limit and cancel live inspection` into `PMM-MCP-GA`, with the Feature Build link.
