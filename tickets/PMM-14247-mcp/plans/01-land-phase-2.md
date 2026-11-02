# Land the phase 2 branches Implementation Plan

> Execution: see [00](00-roadmap.md#how-to-execute-these-plans).

**Goal:** Get the phase 2 work already written onto `PMM-MCP-GA` through its open PRs, percona/pmm#6099, #6100 and #6101, and replace the design files there with pointers to this folder.

**Architecture:** #6100 (`PMM-15529-top-queries-reporting`) is stacked on #6099, and #6101 (`PMM-15529-schema-multi-table`) on #6100. Both branches sit on `PMM-MCP-GA` from before #6068 was squash-merged, so merging them would replay PMM-15528's commits. The PRs stay: each one's branch is rebuilt from `PMM-MCP-GA` with a cherry-pick of its own commits, force-pushed, and the PR retargeted to `PMM-MCP-GA`.

**Tech Stack:** git, `gh`, Go 1.27, go-sdk v1.8.0.

**Spec:** [spec.md §3, §6.5](../spec.md#65-landing-order); roadmap [00](00-roadmap.md).

## Global Constraints

- PRs into `PMM-MCP-GA`, with `PMM-MCP-GA` behind 0 against `main` before each PR ([00](00-roadmap.md#branch-and-pr-rules)).
- No code changes beyond conflict resolution, so each rebuilt PR shows the changes its reviewers were asked to review.
- Each rebuilt branch is force-pushed once, before review starts: neither #6100 nor #6101 has a review as of 2026-11-02. Review rounds after that add new commits, as usual.
- Commit identity of the cherry-picks is kept (`git cherry-pick -x`), so authorship and the original commit stay visible.
- The repository deletes a PR's branch when it merges. A PR whose base is that branch is retargeted to `PMM-MCP-GA` before its base PR merges.

## Review Focus

- **A cherry-pick that resolves a conflict by taking `PMM-MCP-GA`'s side silently drops part of the original commit.** After each pick, `git range-diff` of the original commits against the new ones must show only the added `(cherry picked from commit …)` line and changed context lines; Tasks 2 and 3 run it.
- **D10 in `DECISIONS.md`** arrives with `bcfe4b460`. Task 4 replaces the file after Task 2 has merged, and its pointer keeps D10 (it is recorded in ADR-07 already).

---

### Task 1: Merge #6099 (QAN column catalogue)

**Files:** none beyond the PR's own.

- [ ] **Step 1: Bring the PR branch up to date**

```bash
git fetch origin main PMM-MCP-GA PMM-15529-qan-column-catalogue
git rev-list --count origin/PMM-MCP-GA..origin/main
git checkout PMM-15529-qan-column-catalogue && git merge --no-edit origin/PMM-MCP-GA
```
Expected: `0` (behind 0; otherwise merge `main` into `PMM-MCP-GA` first, [00](00-roadmap.md#branch-and-pr-rules)), then "Already up to date" or a clean merge (the branch merged `PMM-MCP-GA` at `c22620805`). On a conflict, keep both `PMM-MCP-GA`'s change and the PR's, regenerate any generated file with `make gen` (00), commit the merge as a new commit, and push it: #6099 is not force-pushed.

- [ ] **Step 2: Run the package tests and the linter**

Run: `go test ./managed/services/mcp/... && bin/golangci-lint run ./managed/services/mcp/...`
Expected: `ok`, no findings. `TestQANColumnsMatchQANAPI2` passes.

- [ ] **Step 3: Retarget #6100, then merge #6099**

```bash
gh pr edit 6100 --repo percona/pmm --base PMM-MCP-GA
```
#6100's diff looks wrong until Task 2 force-pushes its branch. Then push, get the review, and squash-merge #6099 into `PMM-MCP-GA`.

### Task 2: Rebuild #6100, `pmm_top_queries` reporting (`bcfe4b460`)

**Files:** as in `bcfe4b460`: `managed/services/mcp/tools_qan.go`, `tools_qan_test.go`, `qan_columns.go`, `qan_columns_test.go`, `DECISIONS.md`, `testdata/report*.json`; `api-tests/mcp/mcp_test.go` (`TestTopQueriesGroupBy`); `documentation/docs/api/mcp.md`.

- [ ] **Step 1: Rebuild the branch after Task 1 merged**

```bash
git fetch origin PMM-MCP-GA PMM-15529-top-queries-reporting
git log --oneline --no-merges -2 origin/PMM-15529-top-queries-reporting
git checkout -B PMM-15529-top-queries-reporting origin/PMM-MCP-GA
git cherry-pick -x bcfe4b460
```
Expected: the log shows `bcfe4b460` on top of `17dd6b0fa` (#6099's catalogue commit). A newer commit on top was pushed after this plan: cherry-pick it too, and include it in step 2. The pick applies; a conflict, if any, is in `qan_columns.go` or `tools_qan.go` against #6099's squash.

- [ ] **Step 2: Check nothing of the original was dropped**

Run: `git range-diff bcfe4b460^! HEAD^!`
Expected: one pair, marked `=`, or `!` where the only differences are the `(cherry picked from commit bcfe4b460…)` line and context lines. A changed `+` or `-` line is a dropped or altered change: restore it.

- [ ] **Step 3: Run the tests**

Run: `go test ./managed/services/mcp/ -run 'TestTopQueries|TestOrderByRanking|TestQANColumnsMatchQANAPI2|TestQANValuesAreChecked' -v && go test ./managed/services/mcp/...`
Expected: PASS.

- [ ] **Step 4: Force-push and check #6100**

```bash
git push --force-with-lease origin PMM-15529-top-queries-reporting
gh pr view 6100 --repo percona/pmm --json baseRefName --jq .baseRefName
```
Expected: `PMM-MCP-GA`, and the PR shows one commit. A Feature Build builds from the pushed branch, so the push comes first; no review has been submitted on #6100 yet.

- [ ] **Step 5: Verify live.** On a Feature Build of the pushed branch ([00](00-roadmap.md#terms)), run `go test ./api-tests/mcp/ -run TestTopQueriesGroupBy -v -pmm.server-url=https://admin:<password>@<server>/ -pmm.server-insecure-tls`, then the triage ([00](00-roadmap.md#verification-before-each-pr)). Expected: PASS; `pmm_top_queries` with `group_by=username` reports rows and a total. Add the Feature Build link to #6100.

- [ ] **Step 6: Retarget #6101, then merge #6100**

```bash
gh pr edit 6101 --repo percona/pmm --base PMM-MCP-GA
```
Get the review and squash-merge #6100 into `PMM-MCP-GA`.

### Task 3: Rebuild #6101, `pmm_get_schema` for several tables (`191f2dd82`, `cf47079e6`, `b2bf61618`)

**Files:** as in those commits: `managed/services/mcp/tools_actions.go`, `tools_actions_test.go`, `api-tests/mcp/mcp_test.go`, `documentation/docs/api/mcp.md`.

- [ ] **Step 1: Rebuild the branch after Task 2 merged**

```bash
git fetch origin PMM-MCP-GA PMM-15529-schema-multi-table
git log --oneline --no-merges -4 origin/PMM-15529-schema-multi-table
git checkout -B PMM-15529-schema-multi-table origin/PMM-MCP-GA
git cherry-pick -x 191f2dd82 cf47079e6 b2bf61618
```
Expected: the log shows `b2bf61618`, `cf47079e6` and `191f2dd82` on top of `bcfe4b460`. A newer commit on top is picked too, as in Task 2 step 1, and step 2's ranges grow by one.

- [ ] **Step 2: Check nothing was dropped**

Run: `git range-diff 191f2dd82^..b2bf61618 HEAD~3..HEAD`
Expected: three pairs, each `=` or `!` with only the `(cherry picked from commit …)` line and context lines changed, as in Task 2 step 2.

- [ ] **Step 3: Run the tests**

Run: `go test ./managed/services/mcp/ -run 'TestSchemaTool|TestSchemaManyTables|TestActionDeadlineIsPerCall|TestMapActionError|TestExplainTool' -v && go test ./managed/services/mcp/...`
Expected: PASS.

- [ ] **Step 4: Force-push and check #6101**

```bash
git push --force-with-lease origin PMM-15529-schema-multi-table
gh pr view 6101 --repo percona/pmm --json baseRefName --jq .baseRefName
```
Expected: `PMM-MCP-GA`, and the PR shows three commits; no review has been submitted on #6101 yet.

- [ ] **Step 5: Verify live.** On a Feature Build of the pushed branch, run `go test ./api-tests/mcp/ -run TestExplainMySQLRunsLive -v` with the flags of Task 2 step 5, then `pmm_get_schema` with three tables of a MySQL schema and `info_types: all`. Expected: PASS; three blocks, each with DDL and indexes. Add the Feature Build link, get the review, and squash-merge #6101.

### Task 4: Point `PMM-MCP-GA`'s design files to this folder

Runs after Task 2 has merged, so D10 is in `DECISIONS.md` before the file is replaced, and after [pmm-specs#4](https://github.com/Percona-Lab/pmm-specs/pull/4) merges, so the links resolve on `main`. If `DECISIONS.md` conflicts with a later change to it, keep the pointer, and move that change's decision into this folder through a pmm-specs PR.

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
