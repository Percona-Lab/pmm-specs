# 03: Automated HA tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. For the test-authoring details use pmm-qa:add-ha-test; for case IDs pmm-qa:test-cases and pmm-qa:zephyr.

**Goal:** Spec §6 cases T1–T9 run automatically against a PMM HA install built from plans 01–02.

**Architecture:** Playwright tests in `e2e_tests/tests/ha/`, using the existing `k8sHelper`, `haClusterHelper` and `haBackupHelper` fixtures plus one new helper for per-pod ClickHouse access. The non-destructive check runs in the default `@pmm-ha` suite; tests that drop databases, delete volumes, create splits or restore use their own tags. The tests never fix anything themselves: they create a broken state and wait for qan-api2 or `pmm-backup.sh` to fix it.

**Tech Stack:** Playwright + TypeScript (`e2e_tests/`), kubectl through `K8sHelper`, the Jenkins job `pmm3-ha-tests` (`TAGS_FOR_TESTS`) and `.github/workflows/ha-e2e-tests.yml` (`tags_for_tests`).

**Spec:** [`../spec.md`](../spec.md) §6, D8; plans 01–02.

## Global Constraints

The roadmap's global constraints apply. In addition:
- **Code base:** percona/pmm-qa `main` at `7b45d54`; branch `PMM-15785-qan-clickhouse-db`.
- **Tags:** `--grep` matches by substring (`e2e_tests/tests/ha/upgrade/AGENTS.md:63-65`). Use:
  - `@pmm-ha` for T1 (non-destructive);
  - `@ha-clickhouse-consistency` for T2–T6. These are destructive, so the tag must not start with `@pmm-ha`;
  - `@ha-backup-restore` for T7–T9, the same tag as `backupRestore.test.ts` (PMM-T2377).
  Add the new tag to the list between the `E2E-TAGS-START` markers in `e2e_tests/README.md`.
- **Titles:** `'PMM-Txxxx - Verify … @tag'` (`AGENTS.md:215-216`). Get real PMM-T IDs in Task 1, and add each to `e2e_tests/helpers/versionGates.ts` `minPmmVersion` with the release that ships PMM-15785.
- **Secrets:** read the ClickHouse password from `pmm-secret` and never log it. Mirror `HaBackupHelper.clickHouseQuery` (`e2e_tests/helpers/haBackup.helper.ts:48`), which avoids `assertSuccess` for this reason.
- **QAN ingest:** the job registers at least one database service with QAN (pmm-qa `setup_services`), so the leader writes and `writerPod()` can find it. `beforeAll` fails fast when no pod received a QAN insert in the last 5 min.
- **Timing:** qan-api2's routine runs every 10 min (plan 01 Task 5). Waits for a fix use 15 min.
- **Counts:** `cutoff` is 10 min before the test starts, so late QAN buckets and live ingest do not change the rows compared. Rows the test inserts carry `service_name = 'e2e-stray'`, are excluded from `checksum`, and are counted on their own.
- **Each destructive test leaves the cluster consistent:** `afterEach` calls `waitConsistent(Timeouts.THIRTY_MINUTES)`. The specs run serially, so a timeout stops the rest of the file instead of testing on a broken cluster.

## Review Focus

1. **The routine fixes a node before the test asserts the broken state.** Expected: tests assert the broken state right after creating it, and `createStray` drops and recreates `pmm` in one multi-statement call. Test: T2 asserts "missing" before waiting (Task 3).
2. **qan-api2's routine fixes the split before the restore in T8 starts.** Expected: T8 still passes (the outcome is the same) and reports which of the two fixed it from the restore job log; the restore's own fix is covered by plan 02's unit tests and live replay. Test: T8 (Task 4).
3. **Running against a release without PMM-15785.** Expected: skipped by `versionGate`, not failed. Test: `minPmmVersion` entries (Task 1).
4. **ClickHouse pods named differently** (another release name). Expected: pods are found by label, not by name. Test: `HaClickHouseHelper.pods()` uses the label selector (Task 2).

---

### Task 1: Test cases in Zephyr

**Files:** none in the repo. The cases go to Zephyr, linked to PMM-15785.

- [ ] **Step 1:** Draft T1–T9 with pmm-qa:test-cases from spec §6: one case per row, with the pass criteria copied from the table. Get the draft reviewed and publish it.
- [ ] **Step 2:** Record the PMM-T IDs in the PR description of this plan's branch, and add them to `versionGates.ts` once the fix version is set.

---

### Task 2: `HaClickHouseHelper`

**Files:**
- Create: `e2e_tests/helpers/haClickHouse.helper.ts`
- Modify: `e2e_tests/fixtures/pmmTest.ts` (register the `haClickHouseHelper` fixture next to `haBackupHelper` at :163)
- Test: `e2e_tests/tests/ha/clickhouseConsistency.test.ts` (T1 uses it first)

**Interfaces:**
- Consumes: `K8sHelper` (`execInPod`, `getPodNames`, `getSecretValue`, `exec`, `deletePod`).
- Produces `export default class HaClickHouseHelper` with:
  - `pods(): string[]` — label `clickhouse.altinity.com/chi`, sorted, excluding Keeper pods.
  - `query(pod: string, sql: string): string` — runs in container `clickhouse`, with `--multiquery`. The password goes in through the environment, not on the command line.
  - `pmmUuids(): Record<string, string>` — `''` for a pod without `pmm`.
  - `rows(pod: string, where: string): number` — `count()` of `pmm.metrics` after `SYSTEM SYNC REPLICA pmm.metrics`.
  - `checksum(pod: string, cutoff: number): string` — `count()` and `sum(cityHash64(queryid, service_name, period_start, num_queries))` for `period_start < cutoff AND service_name != 'e2e-stray'`.
  - `writerPod(): string` — the pod with the most `Insert` rows into `pmm.metrics` in `system.query_log` over the last 2 minutes.
  - `dropPmm(pod: string): void`.
  - `resetVolume(pod: string): Promise<void>` — deletes the pod's PVC and the pod, then waits until it is Ready.
  - `createStray(pod: string, rows: number, opts?: { sharedPaths?: boolean }): string` — plan 01 Task 6 Step 5 in one `query` call: drop and create `pmm` with a new UUID, create the tables from another pod's `SHOW CREATE TABLE` with the `UUID` clause and engine arguments removed, copy the `schema_migrations` rows, then insert `rows` rows with `service_name = 'e2e-stray'` over 3 days. With `sharedPaths`, each table keeps the main table's `zookeeper_path` from `system.replicas` as an explicit engine argument (the restore-made split), with `database_replicated_allow_replicated_engine_arguments = 1` passed on the call. Returns the new UUID.
  - `waitConsistent(timeout = Timeouts.FIFTEEN_MINUTES): Promise<void>` — polls until all pods report one UUID and equal `rows` for `period_start < now() - 10 min`.

- [ ] **Step 1: Write T1** in `clickhouseConsistency.test.ts`: `'PMM-Txxxx - Verify every ClickHouse replica has the same pmm database @pmm-ha'`. The helper reports 3 pods with one non-empty UUID.
- [ ] **Step 2: Run** `npx playwright test --grep "PMM-Txxxx"` against the Feature Build install → FAIL (no helper).
- [ ] **Step 3: Implement** the helper and the fixture.
- [ ] **Step 4: Run** → PASS; `npm run lint` and `npm run typecheck` in `e2e_tests` → clean.
- [ ] **Step 5: Commit** `PMM-15785 Add HaClickHouseHelper and the consistency check`.

---

### Task 3: Fix tests (T2–T6)

**Files:**
- Create: `e2e_tests/tests/ha/clickhouseRepair.test.ts` (tag `@ha-clickhouse-consistency`, `test.describe.configure({ mode: 'serial', retries: 0 })`, `pmmTest.setTimeout(Timeouts.SIXTY_MINUTES)`)
- Modify: `e2e_tests/README.md` (tag list)

**Interfaces:**
- Consumes: Task 2, `haClusterHelper.failoverLeader`.

Each body starts with `cutoff`, `before = checksum(pods[0], cutoff)`, and `target` = a pod that is not `writerPod()`.

| Case | Body | Assertions |
|---|---|---|
| T2 | `dropPmm(target)` | right after: `pmmUuids()[target] === ''`; within 15 min: the same UUID as the others, the leader's qan-api2 log shows a `create` for `target`, `checksum` equals `before` on every pod |
| T3 | `resetVolume(target)`; then `resetVolume(writerPod())` and `supervisorctl restart qan-api2` in the leader PMM pod, so it starts against the reset node (the Service's ClientIP affinity keeps the same node) | within 15 min after each: the original UUID on the reset node; `checksum` equals `before` on every pod; after the second, the leader's qan-api2 log shows retries and no exit, and `/v1/qan/metrics:getReport` answers 200 |
| T4 | `createStray(target, 5000)` | right after: `pmmUuids()` holds 2 UUIDs; within 15 min: the original UUID on every pod, `checksum` equals `before` on every pod, no `e2e-stray` rows |
| T5 | `createStray(writerPod(), 5000)` | within 15 min: the original UUID on every pod, although QAN wrote to the stray; `checksum` equals `before` on every pod; no `e2e-stray` rows |
| T6 | `createStray(target, 0, { sharedPaths: true })` | within 15 min: one UUID; `checksum` equals `before` on every pod |

- [ ] **Step 1: Write** T2 and T4 first; run against the FB install → PASS.
- [ ] **Step 2: Write** T3, T5, T6; run → PASS.
- [ ] **Step 3: Commit** `PMM-15785 Test the pmm consistency routine on PMM HA`.

---

### Task 4: Backup and restore tests (T7–T9)

**Files:**
- Create: `e2e_tests/tests/ha/clickhouseBackupRestore.test.ts` (tag `@ha-backup-restore`, the same timeouts and `retries: 0` as `backupRestore.test.ts`)

**Interfaces:**
- Consumes: `haBackupHelper.runBackupJob`, `runRestoreJob`, `latestBackup`, `jobLogs`, `haClusterHelper.ensureServing`; Task 2.

| Case | Body | Assertions |
|---|---|---|
| T7 | backup, then in-place restore | job Complete; one UUID and equal counts on every pod; rows written after the backup are gone |
| T8 | backup; `createStray(pods[0], 5000)` (the first ClickHouse pod, where the restore ran before this change); restore right away. Then backup, `dropPmm(pods[0])`, restore right away. Then backup, `dropPmm` on every pod, restore right away. | each restore job Complete; one UUID and equal counts on every pod; no `e2e-stray` rows. Record from the job log whether the restore or qan-api2 fixed the pod. |
| T9 | restore the latest backup into a second release in namespace `pmm-dr`, prepared as in `charts/pmm-ha/docs/pmm-backup.md` "Preparing a DR namespace", using `new K8sHelper('pmm-dr')` | one UUID and equal counts in `pmm-dr` |

- [ ] **Step 1: `beforeEach`:** `ensureServing` plus `waitConsistent`.
- [ ] **Step 2: Write** T7 and T8; run against the FB install with backups enabled (`k8s/install_pmm_ha.sh --backup-minio` or S3) → PASS.
- [ ] **Step 3: T9.**
  - Add a Jenkins stage that installs the DR release before the test and removes it after, and document the stage in the PR.
  - When the job runs without that stage, T9 calls `test.skip` with the reason ("no pmm-dr release").
- [ ] **Step 4: Commit** `PMM-15785 Test backup and restore consistency`.

---

### Task 5: Run the suites in CI

**Files:** none (Jenkins and the workflow already take tags).

- [ ] **Step 1:** Run `pmm3-ha-tests` with `HELM_CHART_BRANCH=PMM-15785-qan-clickhouse-db`, the Feature Build images, and `TAGS_FOR_TESTS="@pmm-ha|@ha-clickhouse-consistency|@ha-backup-restore"` (pmm-qa:helm-chart-ha-test).
- [ ] **Step 2:** Post the result on the chart and pmm PRs, with the junit link.
- [ ] **Step 3:** T1 runs on every later HA job, since it is in `@pmm-ha`. Five green runs on fresh installs cover spec §6 T1's "at least 5".
