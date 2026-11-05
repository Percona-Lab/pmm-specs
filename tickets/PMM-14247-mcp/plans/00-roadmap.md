# MCP endpoint: roadmap and shared rules

- **Spec:** [spec.md](../spec.md), ADRs in [adr/](../adr/README.md); the folder is under review in [pmm-specs#4](https://github.com/Percona-Lab/pmm-specs/pull/4).
- **Code base:** percona/pmm `PMM-MCP-GA` at `826945906`, plus the phase 2 pull requests in [spec §3](../spec.md#3-where-the-work-stands).
- **Epic:** PMM-14247.
- **Marks:** [V] and [I] as defined at the top of [spec.md](../spec.md): verified, and inferred or not run.
- **References:** "today" and line numbers without a commit refer to `PMM-MCP-GA` at `826945906`.

## How to execute these plans

- The plans are written for an AI coding agent using the superpowers skills (`writing-plans`, `executing-plans`, `subagent-driven-development`). Engineers can read them as checklists; steps use checkbox (`- [ ]`) syntax.
- A full-depth plan is executed task by task.
- A task-level plan is expanded into a full-depth plan, and the expansion is reviewed in a pmm-specs PR, before it starts.
- **Live-check environment:** a disposable PMM Server built from the branch, with MySQL 8.0/8.4, PostgreSQL 17 with pg_stat_monitor, and MongoDB 7 registered. Percona engineers use a Feature Build on a throwaway CHAOS VM. Outside contributors set it up as [`dev/docs/process/running-and-verifying-locally.md`](https://github.com/percona/pmm/blob/main/dev/docs/process/running-and-verifying-locally.md) in percona/pmm describes.
- **Unit tests** run on the development machine and need only Go.

## Terms

- **Plan 0N:** a plan in this folder, by its number. **Step:** only a "Step N" checkbox inside a full-depth plan.
- **Caller:** one set of credentials, identified by the caller key: the service-account token when the request carries one, else the user name of Basic credentials, else the Grafana session cookie ([plan 02](02-origin-and-limits.md), Task 3).
- **Replica:** one pmm-managed instance; a non-HA server has one.
- **Grafana role** (Viewer, Editor, Admin) and **Access Role** (a PMM role with a label filter): always say which one.
- **AI client** (Claude Code, Cursor, …) and **pmm-agent**: never just "agent".
- **Behind 0:** `git rev-list --count origin/PMM-MCP-GA..origin/main` prints `0`, so `PMM-MCP-GA` holds every commit of `main`.
- **Full-depth plan:** every task has its files, interfaces and checkbox steps. **Task-level plan:** tasks only, expanded into a full-depth plan before it starts. Plans 01 to 05 are full-depth, plans 06 to 08 task-level.
- **Feature Build:** Jenkins builds PMM Server and Client images from the branches, through a draft PR in Percona-Lab/pmm-submodules. An outside contributor who can't run one verifies on a local setup and describes that setup in the PR instead.
- **Design review:** the security design review of this folder and `tool-contract.md`; it gates plans 04 to 07. **Implementation review:** the security review of the code, plan 08 Task 1, run after plan 08's Tasks 5 and 6.
- **The caller's service list:** the services the caller can see. From plan 06 on, they are the services in the `up` series of the last hour, read with the caller's credentials and filtered by vmproxy (ADR-08). Until plan 06, the list comes from the inventory API.
- **Filtered:** the backing API applies the caller's Access Roles. **Narrowed:** MCP drops results outside the caller's service list; narrowing is not a security boundary (ADR-03).
- **Live inspection:** a tool call that starts a pmm-agent action on the monitored database (`pmm_get_explain` for MySQL and MongoDB, `pmm_get_schema`). **Passive:** a tool call that only reads what PMM has collected (ADR-05).

## Plans and order

| Plan | Ticket | Needs | Depth |
|---|---|---|---|
| [01 Land the phase 2 branches](01-land-phase-2.md) | PMM-15529 | — | Full-depth |
| [02 Origin check, credentials and live-inspection limits](02-origin-and-limits.md) | PMM-15528 (Origin, credentials), PMM-15529 (limits, cancel) | plan 01 | Full-depth |
| [03 Output contract](03-output-contract.md) | PMM-15530 | plan 02; `tool-contract.md` reviewed (its Task 1) | Full-depth |
| [04 Resolve first](04-resolve-first.md) | PMM-15529 | plans 02, 03; design review | Full-depth |
| [05 Metrics tools](05-metrics.md) | PMM-15790 | plans 02, 03; design review | Full-depth |
| [06 Service list and Access Roles](06-access-roles.md) | PMM-15531 | plans 03 and 04, design review; plan 05 before its Task 4 | Task-level |
| [07 Alerts and Advisors](07-alerts-and-advisors.md) | PMM-15790 | plan 06, design review | Task-level |
| [08 Release](08-release.md) | PMM-15532 | plans 01 to 07; the release gate of [spec §10](../spec.md#10-phase-5-release), PMM-15534 on `main` and merged into `PMM-MCP-GA` included | Task-level |

- **Plan 06** builds the caller's service list from the metric series of the last hour, which vmproxy filters by the caller's Access Roles (ADR-08), uses it for every service lookup, and checks Access Roles end to end. It removes the Viewer rules for `GET /v1/inventory/services` and `/nodes` from #5942.
- **Plan 07** reads alerts from Grafana's alert API and Advisor results from the existing Advisors API, and narrows both to the caller's service list (ADR-03, ADR-17, ADR-18). No plan changes `lbacPrefixes` or adds a pmm-managed API for them.
- **PMM-15534** (ADR-12) is not a plan here. It lands on `main` through its own ticket and PR, and reaches `PMM-MCP-GA` with the next merge of `main`. Plan 08 waits for it.
- ADR-16 is deferred to its own ticket on `main`. ADR-13 (`mcp:use`) ships on PMM-15791 after the MCP release. Neither has a plan here.

Order: plan 01, plan 02, plan 03. The security design review starts once plan 03 Task 1 (`tool-contract.md`) is reviewed, and runs while the rest of plan 03 is built. After plan 03 and the review: plans 04 and 05 in parallel, plan 06 after plan 04 (its Task 4 also waits for plan 05), then plan 07 and plan 08. Plan 06's Access Role matrix covers the query tools, so it needs plan 04.

**Why the contract comes before plans 04 and 05.** Plan 03 puts the contract's plumbing first (typed results, errors, paging, `pmm_catalog`), so the new tools in plans 04 and 05 are written once, in their final shape, instead of text-only and then reworked. The contract document still comes first (plan 03, Task 1).

**Security design review** (spec §3.1, §10.2) reads this folder and `tool-contract.md`, so it runs after plan 03 Task 1. It gates plans 04 to 07, which add data paths and the narrowing to the caller's service list. Plans 01 to 03 add none and don't wait for it. Book it during plan 01; record the outcome on PMM-15532.

## Branch and PR rules

Default for every plan: one plan = one branch = one PR into `PMM-MCP-GA`, opened after the plan's last task. A plan that spans two tickets opens one PR per ticket. Plan 01 is the exception: it lands the three open phase 2 PRs and one new PR.

The last step of every plan: merge `origin/PMM-MCP-GA` into the branch (with `PMM-MCP-GA` behind 0), push it, run a Feature Build from it, run the checks of [Verification, before each PR](#verification-before-each-pr), and open the PR with the Feature Build link (or, for an outside contributor, the description of the local setup).

From PMM-15527:
- Ticket branches are cut from `PMM-MCP-GA`, never from `main`, named `PMM-XXXXX-<2 to 4 words>`, and PR back into `PMM-MCP-GA`.
- Merge `main` into `PMM-MCP-GA` weekly and before every PR, so `PMM-MCP-GA` is behind 0.
- Never hand-merge a file that `make gen` writes: take either side, run `make gen`, commit the result.
- Generated files (`*.pb.go`, `*.pb.gw.go`, swagger) are regenerated, never hand-edited. `make prepare-pr` also reformats them: commit only what `make gen` writes for the branch's own `.proto` changes, and revert the reformatting of generated files the branch doesn't change.
- Test-written files are different. On a conflict in `managed/services/mcp/testdata/tools_list.golden.json`, take either side, keep both sides' entries in the tool lists of the tests (below), re-run `go test ./managed/services/mcp/ -run TestToolsListGolden -update`, and commit the result.
- `PMM-MCP-GA` merges into `main` once, in plan 08.

From `AGENTS.md` in percona/pmm:
- Commit and PR titles `PMM-XXXX Short summary`, signed off (`git commit -s`); a new commit per review round.
- New `.go` files carry the AGPL header; `make check-license` passes.
- Never edit generated files.

Every new MCP tool, from plan 03 on:
- registers in `registerTools` (`managed/services/mcp/mcp.go`) and is added to the name list of `TestInitializeAndListTools` (`mcp_test.go`);
- gets an entry in the tool lists of plan 03's contract tests: `TestUntrustedFieldsMarked`, `TestErrorsCarryNoStructuredContent`, `TestEmptyAndDegradedResults` and `TestRedactionInBothRenderings` (or its exemptions);
- regenerates the golden file with `-update`.

A new `pmmAPI` method regenerates the mock with one command, `go tool mockery --config .mockery.yaml`, run from the repository root; commit only `managed/services/mcp/mock_pmm_api_test.go`. Not `make gen-mocks`, which deletes and regenerates every mock in the repository.

## Verification, every task

- **Unit tests:** `go test ./managed/services/mcp/...`, plus the tests a task adds in another package, by `-run` (some packages, such as `managed/services/grafana`, also hold tests that need a live Grafana).
- **Lint:** `make init` once, then `bin/golangci-lint run ./managed/services/mcp/...`.

## Verification, before each PR

- **Lint and generated files:** `make prepare-pr` (see [Branch and PR rules](#branch-and-pr-rules) for the generated files it reformats).
- **api-tests**, on the live-check environment, from the repository root:

  ```bash
  go test ./api-tests/mcp/ -v -pmm.server-url=https://admin:<password>@<server>/ -pmm.server-insecure-tls
  ```

  `api-tests/mcp` authenticates as `admin` with basic auth from `-pmm.server-url`, and its `TestMain` enables the endpoint for the run and restores the setting afterwards. It therefore can't catch a regression that only a Viewer sees.
- **The triage** (spec §11), by hand, with a Viewer service-account token (created as in `documentation/docs/api/mcp.md`, "Create a token") in an MCP client such as Claude Code: `pmm_inventory` → `pmm_top_queries` → `pmm_query_detail` → `pmm_get_explain` → `pmm_get_schema` → `pmm_get_config`. Then `POST /mcp` answers 404 with the endpoint off.

## Starting values to revisit

These numbers live in [spec §8](../spec.md#8-phase-3-output-contract) and are copied here only as a reminder; plan 08's measurements may change them there.

| Value | Where |
|---|---|
| Live-inspection calls in flight: 2 per caller, 8 per replica | spec §8; plan 02 |
| Metric calls in flight: 4 per caller, 8 per replica | spec §8; plan 05 |
| Inventory 50/200, config variables 200/1000, plan 64 KiB, DDL 32 KiB | spec §8; plan 03 |
| Metrics: 20/100 series, 2,000 points, 16 KiB, 25 s VictoriaMetrics timeout, 7 days read, 4 KiB and 10 selectors | spec §8; plan 05 |
| `pmm_list_metrics` 100/1000, `pmm_alerts` 50/200, `pmm_advisors` 50/200 | spec §8; plans 05, 07 |
