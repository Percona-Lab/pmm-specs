# Alerts and Advisors tools Implementation Plan (task level)

> **For agentic workers:** This plan is task-level. When its step starts ([00](00-roadmap.md)), expand it to full depth with superpowers:writing-plans, then execute with superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** A scoped `GET /v1/alerting/alerts` in pmm-managed and the `pmm_alerts` and `pmm_advisors` tools on top of the scoped APIs.

**Architecture:** pmm-managed reads current alerts from Grafana with the caller's headers, so Grafana's folder permissions apply first, then filters them with plan 06's matcher. The two tools call those APIs through the loopback like every other tool (ADR-03) and return plan 03's typed results.

**Tech Stack:** Go 1.27, protobuf and grpc-gateway (`make gen`), Grafana alerting API, go-sdk v1.8.0.

**Spec:** [ADR-17](../adr/ADR-17-alerts.md), [ADR-18](../adr/ADR-18-advisors.md), [spec §7.2, §7.3, §7.5](../spec.md#72-alerts).

## Global Constraints

- Needs plan 03 (contract) and plan 06 (matcher, scoped paths).
- Each new tool regenerates `testdata/tools_list.golden.json` (`-update`) and lists its Untrusted fields in `TestUntrustedFieldsMarked`.
- `GET /v1/alerting/alerts` at Viewer; Advisor APIs stay Editor, so `pmm_advisors` with a Viewer token is `unauthorized`.
- An alert belongs to the service its labels name; one without service labels is hidden from restricted callers.
- Summaries, descriptions, labels and Advisor texts are marked Untrusted.
- Firing alerts only, silenced or not, with the silence's end time; no history. Read only: no silencing, acknowledging, or running checks.
- `pmm_alerts` 50/200 and `pmm_advisors` 50/200 (default/maximum), paged.
- Proto changes are additive (`buf breaking`).

## Review Focus

- **An alert from a rule that aggregates away `service_name`** is hidden from a restricted caller with a positive and with a negative filter (Task 2).
- **Grafana folder permissions** that hide a rule from a Viewer also hide its alerts, before Access Roles apply (Task 1 records, Task 2 tests).
- **Advisors disabled in settings:** `pmm_advisors` says so with the code the contract sets, not an empty list (Task 4).
- **Annotation text that names another service** is returned as written but never used for matching (Task 2).

---

### Task 1: Settle the Grafana endpoint (gates ADR-17's acceptance)

- On a Feature Build, compare Grafana's Alertmanager API (`/api/alertmanager/grafana/api/v2/alerts`) and its Prometheus-style API (`/api/prometheus/grafana/api/v1/alerts`): what a Viewer gets, how folder permissions narrow it, whether silences and their end times are present.
- Record the choice and the evidence in ADR-17 through a pmm-specs PR.

### Task 2: `GET /v1/alerting/alerts`

**Files:** `api/alerting/v1/alerting.proto` (new `ListAlerts` rpc, `get: "/v1/alerting/alerts"`); `make gen`; `managed/services/alerting/service.go`; a new Grafana client method in `managed/services/grafana/client.go` that calls the chosen endpoint with the caller's headers; `auth_server.go` (`GET /v1/alerting/alerts` at Viewer; scoped path from plan 06).
- Response per alert: name, severity, labels, summary, description, starts_at, silenced, silenced_until, a PMM URL; paging.
- Tests: fake Grafana with alerts for two services and one without service labels; a restricted Viewer with `{service_name="a"}` and with `{service_name!="production"}` sees only the owned alerts; Admin sees all.

### Task 3: `pmm_alerts`

**Files:** `managed/services/mcp/tools_alerts.go`, tests; `pmmAPI` gains the alerts call.
- Inputs: `service_id`, `service_name`, `node_name`, `severity`, `limit`, `offset`. Output per plan 03 with `pmm_url` per alert; Untrusted marks.
- Tests: filters, paging, untrusted fields in the golden file, `unauthorized` passthrough.

### Task 4: `pmm_advisors`

**Files:** `managed/services/mcp/tools_advisors.go`, tests.
- Calls `GET /v1/advisors/failedServices` and `GET /v1/advisors/checks/failed`; returns failed checks per service with check, severity, summary, description, read-more link; filters by service and severity; pages.
- Tests: Editor gets results; Viewer gets `unauthorized`; Advisors disabled gives the contract's code.

### Task 5: api-tests and docs

- api-tests on a server with firing alerts and failed checks; the restricted-role cases of spec §7.5 for both tools.
- `documentation/docs/api/mcp.md`: both tools, and that `pmm_advisors` needs an Editor token.
