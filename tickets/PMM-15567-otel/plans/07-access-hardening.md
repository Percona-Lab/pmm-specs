# OTel 07: Access Hardening of Existing Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Label-based access control applies consistently to every read path that serves monitoring data: ClickHouse-backed Grafana panels, every QAN endpoint, and every kind of credential. The labels that LBAC matches on can come only from PMM inventory. These fixes also make plan 06 sound, because LBAC for logs relies on the same guarantees.

**Architecture:** Four independent fixes:
1. a Grafana-fork plugin middleware;
2. a prefix fix in the auth server plus filtering in qan-api2's detail queries;
3. an explicit LBAC rule for service-account and anonymous credentials;
4. an ingest-side label-precedence fix in pmm-managed's QAN client.

**Tech Stack:** Go (pmm-managed, qan-api2, the Grafana fork), nginx config.

**Spec:** analysis §7.1 and §10 and decision D17. File the fixes in the PMM Jira project per `SECURITY.md`, so that Percona's fix timelines apply. This plan says what to change and how to test it; per `AGENTS.md`, keep exploit detail out of PR descriptions as well.

## Global Constraints

The roadmap's global constraints apply. In addition:
- **Fail closed.** A restricted request that can't be filtered is denied, never served unfiltered.
- **Full-access users see no change:** Admins with the default "Full access" role, and every user when LBAC is disabled.
- **Each task merges on its own:** one ticket and one PR. Task 2 has merged (PMM-15697); the rest go in this order: Task 1, Task 4, Task 3. That order puts the narrowest behaviour change first.
- **`<KEY>`** is the Jira key filed per `SECURITY.md` before the task starts; the branch is `<KEY>-<words>`.

## Review Focus

1. **A restricted user opening one of the six shipped dashboards that use the `ClickHouse` datasource.** Expected: those panels show "not available to users restricted by access roles". Every other panel still works. Test in Task 1.
2. **LBAC disabled.** Expected: no change for anyone, on every path touched here. Test in each task's "LBAC disabled" case.
3. **A user with two roles, one of them with an empty filter.** Expected: full access, the same as today (`auth_server.go:446-494`). Test in Task 2.
4. **An external integration using a Viewer service-account token to read `/prometheus/api/v1/query`.** Expected: it gets the default role's filters when LBAC is on. The release notes announce this behaviour change. Test in Task 3.
5. **A query comment whose label key matches an inventory custom label.** Expected: the inventory value is stored, and the comment value is dropped for that key. Test in Task 4.

---

### Task 1: ClickHouse datasources honour LBAC

**Files** (in percona/grafana, branch `<KEY>-clickhouse-lbac`):
- Create:
  - `pkg/services/pluginsintegration/clientmiddleware/percona_clickhouse_lbac_middleware.go`
  - `pkg/services/pluginsintegration/clientmiddleware/percona_clickhouse_lbac_middleware_test.go`
- Modify: `pkg/services/pluginsintegration/pluginsintegration.go` (:222-223): register it next to `NewPerconaForwarderHTTPClientMiddleware`, and next to plan 03's `NewPerconaOtelAdminMiddleware` if that has merged.

**Interfaces:**
- Produces `func NewPerconaClickHouseLBACMiddleware() plugins.ClientMiddleware`. For `QueryData` and `CallResource`, when the datasource's plugin type is `grafana-clickhouse-datasource` **and** the incoming HTTP request carries a non-empty `X-Proxy-Filter`, it returns an error that maps to HTTP 403 with the message "ClickHouse data is not available to users restricted by access roles".
  - Read the header from the incoming request in the context, the same way `forwarded_percona_token_middleware.go:30-65` does.
  - nginx sends the header only for restricted users (`managed/services/grafana/auth_server.go:446-494`), so a full-access user is unaffected.

- [ ] **Step 1: Write the failing test.** `TestClickHouseLBACMiddleware`, table-driven:
  - ClickHouse datasource, `X-Proxy-Filter` set: 403, and the next handler is not called.
  - ClickHouse datasource, no header: passes.
  - Prometheus datasource, header set: passes.
  - Run every case through both `QueryData` and `CallResource`.
- [ ] **Step 2: Run it.** `go test ./pkg/services/pluginsintegration/clientmiddleware/ -run ClickHouseLBAC`. Expected: FAIL, the function is undefined.
- [ ] **Step 3: Implement** the middleware and its registration.
- [ ] **Step 4: Run it again.** Same command. Expected: PASS. Then on a Feature Build with LBAC on, check as a user with role `{environment="x"}`:
  - `POST /graph/api/ds/query` to the `ClickHouse` datasource returns 403;
  - the Metrics panels still render;
  - as Admin with full access, the ClickHouse panels render.
- [ ] **Step 5: Commit.** `git commit -s -m "<KEY> Apply access roles to ClickHouse datasources"`

### Task 2: LBAC on every QAN endpoint (done by PMM-15697, `a98506570`)

PMM-15697 added `/v1/qan:` to `lbacPrefixes`, filters the reads in `qan-api2/models/metrics.go`, and denies a selector that doesn't parse.

- [ ] **Step 1: Check the rest.** The three service-scoped lookups (`QueryExists`, `SchemaByQueryID`, `ExplainFingerprintByQueryID`) return `NotFound` for a service the user's filter hides. If they don't, that is the only remaining change; give it its own ticket.

### Task 3: An explicit LBAC rule for service-account and anonymous credentials

**Files:**
- Modify:
  - `managed/services/grafana/auth_server.go` (`maybeAddLBACFilters` ~:372-416; the `userID <= 0` early return at :391-396)
  - `managed/services/grafana/client.go` (:288-300, :545-560): expose the role of a service-account token
- Test:
  - `managed/services/grafana/auth_server_test.go`
  - `api-tests/server/auth_test.go`
- Docs: the release note and the access-control page (in the release docs PR)

**Interfaces:**
- The rule. It is a decision for the security reviewer (PMM-15591); this is the recommended option:
  - When LBAC is enabled, a request on an LBAC path from a service-account token whose role is not Admin gets the filters of the **default role** (`settings.default_role_id`), as a new user would.
  - An anonymous request gets the same.
  - Admin-role tokens, such as pmm-agent node tokens, keep today's behaviour.
  - If the default role's filter can't be read, deny.
- Produces `func (s *AuthServer) filtersForPrincipal(ctx context.Context, p principal) ([]string, error)`, with `principal{UserID int; IsServiceAccount bool; Role role}`.

- [ ] **Step 1: Write the failing tests.**
  - `TestLBACServiceAccountViewerGetsDefaultRole`: the default role's filter is `{environment="dev"}`, so the `X-Proxy-Filter` header contains it.
  - `TestLBACServiceAccountAdminUnfiltered`.
  - `TestLBACAnonymousGetsDefaultRole`.
  - `TestLBACDisabledNoFilterForTokens`.
- [ ] **Step 2: Run them.** `cd managed && go test ./services/grafana/ -run 'ServiceAccount|Anonymous|LBACDisabled'`. Expected: FAIL.
- [ ] **Step 3: Implement** the rule.
- [ ] **Step 4: Run them again.** Same command, then `make prepare-pr`. Expected: PASS. Then run an api-test with a Viewer service-account token against `/prometheus/api/v1/query`: with LBAC on, only series the default role allows come back.
- [ ] **Step 5: Commit.** `git commit -s -m "<KEY> Apply the default role to non-Admin tokens"`

### Task 4: LBAC-relevant labels come only from inventory

**Files:**
- Modify:
  - `managed/services/qan/client.go` (~:425-432, the `maps.Copy` of query comments): replace `maps.Copy(labels, m.Common.Comments)` with a merge that never overwrites a key that already exists in `labels`, which holds the inventory custom labels.
  - The same function: drop comment labels whose key is a standard label (`environment`, `cluster`, `replication_set`, `region`, `az`, `node_model`, `machine_id`, `container_id`, `container_name`, and the identity keys deleted at :397-405). Those are columns filled from inventory.
- Test: `managed/services/qan/client_test.go`

**Interfaces:**
- Produces `func mergeCommentLabels(inventory, comments map[string]string) map[string]string`.
- **Residual, a decision for the security reviewer:** a comment label can still add a **new** key that a role matches on. If that is not acceptable, store comment labels under the prefix `comment.` and exclude them from LBAC matching in qan-api2. The QAN filter UI would show the prefix. Record the decision in the PR.

- [ ] **Step 1: Write the failing test.**
  ```go
  func TestMergeCommentLabels(t *testing.T) {
      got := mergeCommentLabels(map[string]string{"team": "billing"}, map[string]string{"team": "payments", "environment": "prod", "route": "/pay"})
      assert.Equal(t, map[string]string{"team": "billing", "route": "/pay"}, got)
  }
  ```
  Add a `Collect` test: a bucket whose comments carry `team=payments`, for a service with the custom label `team=billing`, is sent to qan-api2 with `team=billing`.
- [ ] **Step 2: Run it.** `cd managed && go test ./services/qan/ -run 'MergeCommentLabels|Collect'`. Expected: FAIL.
- [ ] **Step 3: Implement** `mergeCommentLabels` and use it.
- [ ] **Step 4: Run it again.** Same command, then `make prepare-pr`. Expected: PASS.
- [ ] **Step 5: Commit.** `git commit -s -m "<KEY> Keep inventory labels over query comment labels"`
