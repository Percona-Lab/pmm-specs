# Land the phase 2 branches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the phase 2 work already written (#6099, `PMM-15529-top-queries-reporting`, `PMM-15529-schema-multi-table`) onto `PMM-MCP-GA`, and replace the design files there with pointers to this folder.

**Architecture:** The two branches without a PR are stacked on the catalogue commit and on `PMM-MCP-GA` from before #6068 was squash-merged, so merging them would replay PMM-15528's commits. Each lands instead as a cherry-pick of its own commits onto a fresh branch from `PMM-MCP-GA`.

**Tech Stack:** git, Go 1.27, go-sdk v1.8.0.

**Spec:** [spec.md §3, §6.5](../spec.md#65-landing-order); roadmap [00](00-roadmap.md).

## Global Constraints

- Branches from `PMM-MCP-GA`, PRs into `PMM-MCP-GA`, `behind 0` against `main` before each PR ([00](00-roadmap.md)).
- No code changes beyond conflict resolution: these commits were reviewed as written.
- Commit identity of the cherry-picks is kept (`git cherry-pick -x`), so authorship and the original commit stay visible.

## Review Focus

- **A cherry-pick that resolves a conflict by taking `PMM-MCP-GA`'s side silently drops part of the original commit.** After each pick, `git diff <original-commit>^! -- managed/services/mcp/ api-tests/mcp/ documentation/` against the new commit's diff must show only context differences; Tasks 2 and 3 check it.
- **D10 in `DECISIONS.md`** arrives with `bcfe4b460`; Task 4 must carry it into the pointer, not drop it (it is recorded in ADR-07 already).

---

### Task 1: Merge #6099 (QAN column catalogue)

**Files:** none beyond the PR's own.

- [ ] **Step 1: Bring the PR branch up to date**

```bash
git fetch origin PMM-MCP-GA PMM-15529-qan-column-catalogue
git checkout PMM-15529-qan-column-catalogue && git merge --no-edit origin/PMM-MCP-GA
```
Expected: "Already up to date" or a clean merge (the branch merged `PMM-MCP-GA` at `c22620805`).

- [ ] **Step 2: Run the package tests and the linter**

Run: `go test ./managed/services/mcp/... && bin/golangci-lint run ./managed/services/mcp/...`
Expected: `ok`, no findings. `TestQANColumnsMatchQANAPI2` passes.

- [ ] **Step 3: Push, get the review, squash-merge #6099 into `PMM-MCP-GA`.**

### Task 2: Land `pmm_top_queries` reporting (`bcfe4b460`)

**Files:** as in `bcfe4b460`: `managed/services/mcp/tools_qan.go`, `tools_qan_test.go`, `qan_columns.go`, `qan_columns_test.go`, `DECISIONS.md`, `documentation/docs/api/mcp.md`, `testdata/report_*.json`.

- [ ] **Step 1: Cut the branch after Task 1 merged**

```bash
git fetch origin PMM-MCP-GA && git checkout -b PMM-15529-top-queries-flexible origin/PMM-MCP-GA
git cherry-pick -x bcfe4b460
```
Expected: applies; a conflict, if any, is in `qan_columns.go` or `tools_qan.go` against #6099's squash.

- [ ] **Step 2: Check nothing of the original was dropped**

Run: `diff <(git show bcfe4b460 --format= -U0 | grep '^[+-]' | grep -v '^[+-][+-]') <(git show HEAD --format= -U0 | grep '^[+-]' | grep -v '^[+-][+-]')`
Expected: no output, or only lines that #6099 already contains.

- [ ] **Step 3: Run the tests**

Run: `go test ./managed/services/mcp/ -run 'TestTopQueries|TestOrderByRanking|TestQANColumnsMatchQANAPI2|TestQANValuesAreChecked' -v && go test ./managed/services/mcp/...`
Expected: PASS.

- [ ] **Step 4: Verify live.** On a Feature Build ([00](00-roadmap.md#verification-every-task)), run `api-tests/mcp` `TestTopQueriesGroupBy` and the triage. Expected: PASS; `pmm_top_queries` with `group_by=username` reports rows and a total.

- [ ] **Step 5: Push and open the PR into `PMM-MCP-GA`, titled `PMM-15529 Extend pmm_top_queries reporting`, with the Feature Build link.**

### Task 3: Land `pmm_get_schema` for several tables (`191f2dd82`, `cf47079e6`, `b2bf61618`)

**Files:** as in those commits: `tools_actions.go`, `tools_actions_test.go`, `api-tests/mcp/mcp_test.go`, `documentation/docs/api/mcp.md`.

- [ ] **Step 1: Cut the branch after Task 2 merged**

```bash
git fetch origin PMM-MCP-GA && git checkout -b PMM-15529-schema-many-tables origin/PMM-MCP-GA
git cherry-pick -x 191f2dd82 cf47079e6 b2bf61618
```

- [ ] **Step 2: Check nothing was dropped**, as in Task 2 step 2, for each of the three commits.

- [ ] **Step 3: Run the tests**

Run: `go test ./managed/services/mcp/ -run 'TestSchemaTool|TestSchemaManyTables|TestActionDeadlineIsPerCall|TestMapActionError|TestExplainTool' -v && go test ./managed/services/mcp/...`
Expected: PASS.

- [ ] **Step 4: Verify live.** `api-tests/mcp` `TestExplainMySQLRunsLive`, then `pmm_get_schema` with three tables of a MySQL schema and `info_types: all`. Expected: three blocks, each with DDL and indexes.

- [ ] **Step 5: Push and open the PR, `PMM-15529 Fetch many tables in pmm_get_schema`.** After it merges, delete the old branches `PMM-15529-top-queries-reporting` and `PMM-15529-schema-multi-table`.

### Task 4: Point `PMM-MCP-GA`'s design files to this folder

Runs after [#4](https://github.com/Percona-Lab/pmm-specs/pull/4) merges, so the links resolve on `main`.

**Files:**
- Modify: `managed/services/mcp/DECISIONS.md` (replace the content)
- Delete: `dev/docs/managed/mcp-access-roles-proposal.md`

- [ ] **Step 1: Replace `DECISIONS.md` with three lines**

```markdown
# MCP decisions

Moved to [Percona-Lab/pmm-specs `tickets/PMM-14247-mcp/`](https://github.com/Percona-Lab/pmm-specs/tree/main/tickets/PMM-14247-mcp): the spec, ADR-01..18 and the plans. D1 to D10 map to ADRs as listed in spec §5.1.
```

- [ ] **Step 2: Delete the proposal; it is ADR-13 now.** Run `git grep -n 'mcp-access-roles-proposal\|DECISIONS.md'` and fix any reference. Expected: none left except the new pointer.

- [ ] **Step 3: Commit `PMM-14247 Point MCP design files to pmm-specs` on branch `PMM-14247-specs-pointer` and open the PR into `PMM-MCP-GA`.**
