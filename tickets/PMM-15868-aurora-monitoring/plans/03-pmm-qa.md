# Aurora monitoring, part 3: pmm-qa tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Aurora tests catch the bugs this epic fixes: Details opened without URL variables, and an Aurora instance missing from the overview.

**Architecture:** Extend the existing CodeceptJS test PMM-T1295 (Aurora Details exists only there) and add the overview to the active Playwright suite next to PMM-T2340.

**Tech Stack:** CodeceptJS (`codeceptjs-e2e/`), Playwright (`e2e_tests/`), TypeScript/JavaScript.

**Spec:** [../spec.md](../spec.md), Detailed Implementation items 19 and 20.

**Repository:** percona/pmm-qa, branch `PMM-15868-aurora-tests`, one PR, run against a Feature Build with plans 01 and 02.

## Global Constraints

* Read `AGENTS.md` and `CLAUDE.md` (house style: minimal comments, never edit tracked config as a workaround) before editing.
* New UI coverage goes to Playwright; CodeceptJS changes only extend PMM-T1295, which exists only there.
* Keep the six existing Details panel titles in `dashboardPage.js`; plan 02 keeps them unchanged.
* Lint with `support_scripts/lint/lint-changed.sh <files>`; commits `PMM-15868 <summary>`, signed off.

## Review Focus

1. **Details opened with no `service_name`**: the dropdown lists the instance. Task 1.
2. **Rows that are empty without a reader or Serverless**: they stay collapsed, so the "no empty graphs" check doesn't count them (it counts visible elements only, `dashboardPage.js:1360`). Task 1.
3. **The overview lists the instance under its cluster, not under `AWS cluster unknown`**, when the client is current. Task 2.

None of the remaining spec cases (old client, stopped exporter, failover) is cheap to automate on the shared QA instances; they stay as manual checks in plan 02.

---

### Task 1: PMM-T1295 opens Details without URL variables

**Files:**
- Modify: `codeceptjs-e2e/tests/verifyAuroraMySQLRemoteInstance_test.js`

**Interfaces:**
- Consumes: `dashboardPage.mysqlAmazonAuroraDetails.url` (unchanged) and the Details dropdowns from plan 02 Task 1.

- [ ] **Step 1: Add the scenario**

`Data(instances).Scenario('PMM-T1295 - Verify MySQL Amazon Aurora Details without URL variables @instances', …)`:
open `dashboardPage.mysqlAmazonAuroraDetails.url` with only `from: 'now-5m'`, wait for the dashboard, and assert that the Service Name dropdown's options include `remoteInstancesHelper.remote_instance.aws.aurora[current].instance_id`; then select it and call `dashboardPage.verifyThereAreNoGraphsWithoutData(0)`.

- [ ] **Step 2: See it fail on a server without plan 02**

Run it against the current dev image (`npx codeceptjs run --grep "without URL variables"` with the suite's usual environment).
Expected: FAIL, the dropdown has no options.

- [ ] **Step 3: See it pass on the Feature Build**

Run the same against the Feature Build with plans 01 and 02.
Expected: PASS, and the existing PMM-T1295 scenarios still pass.

- [ ] **Step 4: Lint and commit**

`support_scripts/lint/lint-changed.sh codeceptjs-e2e/tests/verifyAuroraMySQLRemoteInstance_test.js`; `git commit -s -m "PMM-15868 Check Aurora Details without URL variables"`

### Task 2: Overview in the Playwright suite

**Files:**
- Modify: `e2e_tests/testdata/dashboards.registry.ts` (add `{ folder: 'MySQL', url: 'graph/d/aurora-overview/amazon-aurora-overview' }` next to the Aurora Details entry)
- Modify: `e2e_tests/tests/inventory/remoteInstances.test.ts`

**Interfaces:**
- Consumes: uid `aurora-overview` and the table title `Aurora instances` from plan 02 Task 3; the existing `auroraMysql` test data and `api.remoteInstanceApi`.

- [ ] **Step 1: Add the test**

`pmmTest('PMM-T<new> - Verify Aurora overview lists the instance by cluster @instances', …)`: ensure the Aurora MySQL instance is added (`api.remoteInstanceApi.ensureRemoteService(auroraMysql)`), open `graph/d/aurora-overview/amazon-aurora-overview?from=now-15m`, and, inside `expect(...).toPass` with the `Timeouts` used by PMM-T2340, assert the `Aurora instances` table has a row with `auroraInstanceId` whose cluster cell is not `AWS cluster unknown`.
Get the `PMM-T` key from QA (the `pmm-qa:zephyr` skill creates it).

- [ ] **Step 2: See it fail, then pass**

Run `npx playwright test --grep "Aurora overview"` against the current dev image (FAIL: no dashboard), then against the Feature Build (PASS). The registry change makes `searchDashboards.test.ts` expect the overview in the MySQL folder; run it too.

- [ ] **Step 3: Lint, commit, PR**

Lint the two files; `git commit -s -m "PMM-15868 Test the Aurora overview"`; push and open the PR `PMM-15868 Aurora dashboard tests`, linked from the plan 02 PR.
