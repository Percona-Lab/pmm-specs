# Identity and Access Roles Implementation Plan (task level)

> **For agentic workers:** This plan is task-level. When its step starts ([00](00-roadmap.md)), expand it to full depth with superpowers:writing-plans, then execute with superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Service-account tokens are governed by Access Roles (ADR-12), and pmm-managed's inventory, Advisor and alert APIs apply them through one fail-closed matcher (ADR-16, ADR-08, ADR-18), without filtering Admins.

**Architecture:** `auth_request` resolves a token's user ID, computes the caller's filters for the new scoped paths, and always sends a value there: the selectors, or an explicit empty list for an unrestricted caller or an Admin. nginx sets the header on every location in front of pmm-managed; the gRPC gateway forwards it into metadata; a matcher in pmm-managed accepts exactly one value and filters items by their labels.

**Tech Stack:** Go 1.27, grpc-gateway v2, Prometheus selector parser (as qan-api2), nginx.

**Spec:** [ADR-12](../adr/ADR-12-service-accounts-as-principals.md), [ADR-16](../adr/ADR-16-access-roles-on-pmm-apis.md), [ADR-08](../adr/ADR-08-inventory-under-access-roles.md), [ADR-18](../adr/ADR-18-advisors.md), [spec §9](../spec.md#9-phase-4-identity-and-access-roles). PMM-15534 and PMM-15703 are referenced by key only.

## Global Constraints

- Only `auth_request`'s value reaches the matcher: nginx sets `X-Proxy-Filter` and `X-Proxy-Admin` in `location /v1/` (`proxy_set_header`) and in `/inventory.`, `/management.`, `/server.` (`grpc_set_header`).
- Scoped paths: `GET /v1/inventory/services`, `/v1/inventory/nodes` and their single-object paths, `GET /v1/advisors/failedServices`, `/v1/advisors/checks/failed`, `GET /v1/alerting/alerts` (plan 07), and gRPC `/inventory.v1.ServicesService/`, `/inventory.v1.NodesService/`.
- On scoped paths the header is always set: selectors, or `[]` when Access Control is off, one of the caller's roles has no filter, or the caller is Admin.
- The matcher accepts exactly one value; none, two, or an undecodable one → `PermissionDenied`, path logged at error level.
- A selector matches an item only if the item carries every label the selector names (stricter than PromQL for `!=`, `!~`, and regexes that match the empty string).
- A node is visible when its own labels match or it hosts a visible service.
- vmproxy, qan-api2, and filtering of metrics and QAN for Admins stay as they are.

## Review Focus

- **PMM's own node accounts under a restricted default role:** `pmm-admin list`, `remove`, `unregister` and `pmm-agent setup` behave as before (Task 9).
- **A client that sends its own `X-Proxy-Filter: []`** on the REST or gRPC route still gets its role's filter (Task 10).
- **A new gateway route left out of `lbacPrefixes`** fails CI, not production (Task 8).
- **Two services on one node, a role allowing one:** the other service and its Advisor results are hidden; the node is listed (Task 6, Task 7).
- **Tokens created before the upgrade** start on the default role; the release notes say so (Task 9).

---

### Task 1: Service-account tokens resolve to their user ID (ADR-12)

**Files:** `managed/services/grafana/client.go` (`getRoleForServiceToken`, `authUser` at `:203`), `auth_server.go`; tests in `client_test.go`, `auth_server_test.go`.
- Read `id` from the `GET /api/auth/serviceaccount` response already fetched; set `authUser.userID`.
- Tests: a fake Grafana answer `{"id": 42, "orgId": 1, "role": "Viewer"}` gives user 42; a token seen for the first time gets the default role (`AssignDefaultRole`); its filters then apply on `/v1/qan/` and the datasource proxy.

### Task 2: nginx sets the headers on every route to pmm-managed

**Files:** `build/ansible/roles/nginx/files/conf.d/pmm.conf`; new `managed/services/grafana/pmm_conf_test.go`.
- Add the two headers to `location /v1/` and, with `grpc_set_header`, to the gRPC locations.
- Static test: parse `pmm.conf`; every location whose `proxy_pass` or `grpc_pass` targets `managed-json`, `managed-grpc`, `qan-api-json` or `vmproxy` sets `X-Proxy-Filter` and `X-Proxy-Admin` itself.

### Task 3: Scoped paths always carry a value

**Files:** `managed/services/grafana/auth_server.go` (`lbacPrefixes`, `maybeAddLBACFilters`, the Admin branch at `:352`); `auth_server_test.go`.
- Add the scoped paths to `lbacPrefixes`; on them, set `[]` for Access Control off, an empty-filter role, or role ≥ Admin; otherwise the selectors.
- Tests: table over (path scoped or not) × (Access Control on/off) × (Viewer with filter, Viewer with empty-filter role, Admin with filter): the header value for each; non-scoped paths unchanged.

### Task 4: The gateway forwards the header

**Files:** `managed/cmd/pmm-managed/main.go` (`grpc_gateway.NewServeMux` at `:417`).
- Add an incoming header matcher that passes `x-proxy-filter` into gRPC metadata, keeping the default matcher for the rest.
- Test: an in-process gateway request with the header reaches a handler with exactly one metadata value; a request with two headers yields two values (refused by Task 5).

### Task 5: The matcher

**Files:** new package `managed/services/scope` (`scope.go`, `scope_test.go`).
- `FromContext(ctx) (Filter, error)` reads exactly one `x-proxy-filter` value and decodes it as `auth_server` encodes it; `Filter.Matches(labels map[string]string) bool` with the presence rule; parsed with the selector parser qan-api2 uses.
- Tests: qan-api2's selector cases; negative matchers and empty-matching regexes against items with and without the label; `[]` matches everything; missing, repeated and undecodable values → `PermissionDenied`.

### Task 6: Inventory under Access Roles (ADR-08)

**Files:** `managed/services/inventory/grpc/services_server.go`, `nodes_server.go`, their tests.
- List and get apply the filter to a service's labels plus its node's; a node is visible by its own labels or by hosting a visible service; a hidden object answers `NotFound`.
- Tests: two services on one node with a role allowing one; a node hosting nothing visible is hidden; Admin sees all.

### Task 7: Advisors under Access Roles (ADR-18)

**Files:** `managed/services/management/checks.go` (`ListFailedServices` `:54`, `GetFailedChecks` `:117`), tests.
- Filter by each result's service labels; summaries count visible results only; the role stays Editor.

### Task 8: Route coverage

**Files:** new `managed/services/grafana/route_coverage_test.go`.
- Enumerate the gateway routes of the scoped services (from the generated `*.pb.gw.go` patterns) and their gRPC method names (from `ServiceDesc`); fail when one is not covered by `lbacPrefixes`.

### Task 9: PMM's node accounts, docs and release note

- On a Feature Build with a restricted default role: register a node; `pmm-admin list`, `remove <type>`, `unregister` and a second `pmm-agent setup` behave as on `PMM-MCP-GA` before this plan; record evidence on PMM-15531.
- Update `documentation/docs/api/mcp.md` and the access-control docs: assigning roles to service accounts with `POST /v1/accesscontrol/roles:assign`; a release-notes line that tokens start on the default role.

### Task 10: Access Control matrix and header tests (api-tests)

**Files:** `api-tests/mcp/`, `api-tests/inventory/`.
- Matrix of spec §11, phase 4: Access Control on and off; interactive Viewer, Editor, service token and Admin; one-service role, two roles, a negative filter, the default role; two services on one node; `pmm_inventory`, `pmm_top_queries`, `pmm_query_metrics` and the inventory API return only the allowed data.
- A client-supplied `X-Proxy-Filter: []` on `/v1/inventory/services` and on the gRPC route is replaced by the real filter; two values are refused.
