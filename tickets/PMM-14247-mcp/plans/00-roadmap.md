# MCP endpoint: roadmap and shared rules

- **Spec:** [spec.md](../spec.md), ADRs in [adr/](../adr/README.md). Approved in [#4](https://github.com/Percona-Lab/pmm-specs/pull/4).
- **Code base:** percona/pmm `PMM-MCP-GA` at `826945906`, plus the phase 2 branches in [spec §3](../spec.md#3-where-the-work-stands).
- **Epic:** PMM-14247.

## Plans and order

| Step | Plan | Ticket | Needs | Depth |
|---|---|---|---|---|
| 1 | [01 Land the phase 2 branches](01-land-phase-2.md) | PMM-15529 | — | Full |
| 2 | [02 Origin check and live-inspection limits](02-origin-and-limits.md) | PMM-15528 (Origin), PMM-15529 (limits) | 1 | Full |
| 3 | [03 Output contract](03-output-contract.md) | PMM-15530 | 1; `tool-contract.md` reviewed (its task 1) | Full |
| 4 | [04 Resolve first](04-resolve-first.md) | PMM-15529 | 2, 3; security design review | Full |
| 5 | [05 Metrics tools](05-metrics.md) | PMM-15790 | 2, 3; security design review | Full |
| 6 | [06 Identity and Access Roles](06-access-roles.md) | PMM-15531, PMM-15534, PMM-15536 | — | Task-level |
| 7 | [07 Alerts and Advisors](07-alerts-and-advisors.md) | PMM-15790, PMM-15531 | 3, 6 | Task-level |
| 8 | [08 Release](08-release.md) | PMM-15532 | 1–7 | Task-level |

Steps 4 and 5 can run in parallel, and so can step 6 with 3 to 5. Task-level plans are expanded to full depth, with this skill, when their step starts.

**Difference from spec §3.1.** The spec builds the rest of phase 2 and the metrics tools "to the contract" before the phase 3 code. These plans put the contract's plumbing first (plan 03: typed results, errors, paging, `pmm_catalog`), so the new tools in plans 04 and 05 are written once, in their final shape, instead of text-only and then reworked. The contract document still comes first (plan 03, task 1).

**Security design review** (spec §3.1, §10.2) of the spec gates plans 04 and 05, which add data paths. Plans 01 to 03 add none and don't wait for it. Book it at step 1; record the outcome on PMM-15532.

## Branch and PR rules

From PMM-15527:
- Ticket branches are cut from `PMM-MCP-GA`, never from `main`, named `PMM-XXXXX-<2 to 4 words>`, and PR back into `PMM-MCP-GA`.
- Merge `main` into `PMM-MCP-GA` weekly and before every PR, so `git rev-list --count origin/PMM-MCP-GA..origin/main` is `0`.
- Never hand-merge a generated file: take either side, run `make gen`, commit the result.
- `PMM-MCP-GA` merges into `main` once, in plan 08.

From `AGENTS.md` in percona/pmm:
- Commit and PR titles `PMM-XXXX Short summary`, signed off (`git commit -s`); a new commit per review round.
- New `.go` files carry the AGPL header; `make check-license` passes.
- Never edit generated files.

## Verification, every task

- **Unit tests** run on the runner host (Go only): `go test ./managed/services/mcp/...`, plus the package a task touches.
- **Lint:** `make init` once, then `bin/golangci-lint run ./managed/services/mcp/...`; before a PR, `make prepare-pr`.
- **Live checks** run on a throwaway CHAOS VM, never on the runner: a Feature Build from the branch (`pmm-feature-build` skill) on a VM from `chaos-docker-provisioning`, with MySQL, PostgreSQL and MongoDB services registered, then `api-tests/mcp` with `PMM_ENABLE_MCP=true` and a Viewer service-account token.
- **The triage** (spec §11): `pmm_inventory` → `pmm_top_queries` → `pmm_query_detail` → `pmm_get_explain` → `pmm_get_schema` → `pmm_get_config` with a Viewer token, and `POST /mcp` answering 404 with the endpoint off.

## Starting values to revisit

These numbers are starting values from the spec; plan 08's measurements may change them.

| Value | Where |
|---|---|
| 2 live-inspection calls per caller, 8 per replica | ADR-05, plan 02 |
| 4 metric queries per caller, 8 per replica | ADR-15, plan 05 |
| Inventory 50/200, config variables 200/1000, plan 64 KiB, DDL 32 KiB | spec §8, plan 03 |
| Metrics: 20/100 series, 2,000 points, 16 KiB, 30 s, 7 days read, 4 KiB and 10 selectors | spec §8, plan 05 |
| `stale` after three scrape intervals | ADR-15, plan 05 |
