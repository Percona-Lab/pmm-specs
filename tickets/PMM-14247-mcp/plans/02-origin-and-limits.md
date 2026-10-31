# Origin check and live-inspection limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse cross-site browser requests to `/mcp` (ADR-10), and bound the live-inspection calls one token and one replica can have in flight (ADR-05).

**Architecture:** `Handler` keeps its order: loopback peer, then the enabled switch, then Go's `http.CrossOriginProtection`, then the SDK handler. A small in-memory `limiter` counts calls in flight per caller key and per replica; plan 05 reuses it for metric queries.

**Tech Stack:** Go 1.27 `net/http` (`CrossOriginProtection`, Go 1.25+), go-sdk v1.8.0.

**Spec:** [ADR-10](../adr/ADR-10-nginx-only.md), [ADR-05](../adr/ADR-05-read-only-tools.md), [spec §6.6, §11](../spec.md#66-acceptance).

## Global Constraints

- A disabled endpoint stays invisible: 404 before any Origin check, whatever the request carries.
- Live inspection: at most 2 calls in flight per caller and 8 per replica; the next call answers `rate_limited` at once, never waits.
- The caller key is a hash of `Authorization` and `Cookie`; neither header is logged or stored in clear.
- PostgreSQL's stored plan is passive (ADR-05) and not limited.

## Review Focus

- **An MCP client that sends no `Origin` and no `Sec-Fetch-Site`** (Claude Code, Cursor, curl) must keep working: Task 1 step 1 tests it.
- **A failed or cancelled live call must release its slot,** or a token locks itself out: Task 2 step 1 tests release on error and on context cancellation.
- **One token at its limit must not block another token:** Task 2 step 1 tests two keys.

---

### Task 1: Origin check (ADR-10)

**Files:**
- Modify: `managed/services/mcp/mcp.go` (`New`, where `s.handler` is built)
- Test: `managed/services/mcp/hardening_test.go`

- [ ] **Step 1: Write the failing test `TestOriginCheck`**

Table over raw `POST /mcp` requests to `httptest.NewServer(s.Handler())` (a loopback peer), body `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}`, headers `Content-Type: application/json`, `Accept: application/json, text/event-stream`:

| Case | Extra headers | Enabled | Want status |
|---|---|---|---|
| no browser headers | — | yes | 200 |
| same-origin fetch | `Sec-Fetch-Site: same-origin` | yes | 200 |
| cross-site fetch | `Sec-Fetch-Site: cross-site`, `Origin: https://evil.example` | yes | 403 |
| foreign Origin only | `Origin: https://evil.example` | yes | 403 |
| cross-site, disabled | `Sec-Fetch-Site: cross-site` | no | 404 |

- [ ] **Step 2: Run it to see the cross-site cases fail**

Run: `go test ./managed/services/mcp/ -run TestOriginCheck -v`
Expected: FAIL on the two 403 rows (got 200).

- [ ] **Step 3: Wrap the SDK handler in `New`:** `s.handler = http.NewCrossOriginProtection().Handler(mcp.NewStreamableHTTPHandler(...))`. `Handler()` is unchanged, so the loopback and enabled checks still run first.

- [ ] **Step 4: Run the test and the package**

Run: `go test ./managed/services/mcp/...`
Expected: PASS, including `TestHandlerOnlyServesLoopbackPeers`, `TestServesRequestsProxiedByNginx`, `TestDisabled`.

- [ ] **Step 5: Verify live.** On a Feature Build: `curl -X POST https://<server>/mcp -H 'Origin: https://evil.example' -H 'Sec-Fetch-Site: cross-site' ...` answers 403; Claude Code connected with a token still completes the triage.

- [ ] **Step 6: Commit** `PMM-15528 Refuse cross-site requests to /mcp`.

### Task 2: Live-inspection limits (ADR-05)

**Files:**
- Create: `managed/services/mcp/limits.go`, `managed/services/mcp/limits_test.go`
- Modify: `managed/services/mcp/errors.go` (new code), `mcp.go` (`Service.live`, set in `New`), `tools_actions.go` (`explain`, `schema`), `documentation/docs/api/mcp.md` (errors table)
- Test: `managed/services/mcp/tools_actions_test.go`

**Interfaces:**
- Produces:
  - `type limiter struct` with `func newLimiter(perCaller, total int) *limiter` and `func (l *limiter) acquire(key string) (release func(), ok bool)`; `release` is idempotent.
  - `func callerKey(auth callerAuth) string`: hex SHA-256 of `auth.authorization + "\x00" + auth.cookie`.
  - `codeRateLimited errorCode = "rate_limited"` in `errors.go`.
  - `const maxLiveCallsPerCaller = 2`, `maxLiveCallsPerReplica = 8` in `limits.go`.
  - `func (s *Service) startLive(auth callerAuth) (release func(), err error)`: `err` is a `*toolError` with `codeRateLimited` naming which limit was hit (per token: "at most 2 live-inspection calls in flight per token"; per replica: "the server has 8 live-inspection calls in flight").
- Plan 05 reuses `limiter`, `callerKey` and `codeRateLimited`.

- [ ] **Step 1: Write `TestLimiter` in `limits_test.go`**

```go
l := newLimiter(2, 3)
r1, ok1 := l.acquire("a"); r2, ok2 := l.acquire("a"); _, ok3 := l.acquire("a")
require.True(t, ok1); require.True(t, ok2); require.False(t, ok3)   // per caller
_, okB := l.acquire("b"); _, okC := l.acquire("c")
require.True(t, okB); require.False(t, okC)                         // per replica
r1(); r1()                                                           // idempotent
_, okA := l.acquire("a"); require.True(t, okA)
r2()
```
Plus `TestCallerKey`: equal for equal headers, different when only the cookie differs, never contains the token text.

- [ ] **Step 2: Write `TestLiveInspectionRateLimited` in `tools_actions_test.go`**

With the fixtures `TestSchemaTool` uses, and `key := callerKey(callerAuth{authorization: testToken})`:
- acquire `key` twice on `s.live`, call `pmm_get_schema`: text starts `error: rate_limited`, `isError` true, and the fake PMM recorded no `POST /v1/actions:startServiceAction`;
- release one, call again: success;
- fill 8 slots with other keys, call `pmm_get_explain` for the MySQL fixture: `error: rate_limited`;
- with `key` at 2, `pmm_get_explain` on the PostgreSQL fixture (stored plan) succeeds.

- [ ] **Step 3: Run them to see them fail**

Run: `go test ./managed/services/mcp/ -run 'TestLimiter|TestCallerKey|TestLiveInspectionRateLimited' -v`
Expected: FAIL to compile (`newLimiter` undefined).

- [ ] **Step 4: Implement `limits.go`, the error code and `startLive`; call `startLive` in `schema` before `tableInfo`, and in `explain` on the MySQL and MongoDB paths before `runAction`, with `defer release()`.**

- [ ] **Step 5: Run the package tests**

Run: `go test -race ./managed/services/mcp/...`
Expected: PASS.

- [ ] **Step 6: Document `rate_limited`** in the errors table of `documentation/docs/api/mcp.md`: "Too many live-inspection calls in flight for this token (2) or this server (8). Retry when one finishes."

- [ ] **Step 7: Commit** `PMM-15529 Limit live inspection per token and replica`.
