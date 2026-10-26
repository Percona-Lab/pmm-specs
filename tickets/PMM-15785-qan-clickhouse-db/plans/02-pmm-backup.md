# 02: pmm-backup.sh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pmm-backup.sh` handles QAN data correctly across ClickHouse pods:
- a backup runs on the pod with the most rows;
- a restore refuses only when a ClickHouse or Keeper pod does not answer. After stopping PMM and downloading the backup, it brings every pod to one `pmm`, then restores;
- a restore fails, with PMM left scaled down, when ClickHouse comes back inconsistent or with a row count different from the backup.

**Architecture:** New POSIX-sh helpers in `charts/pmm-ha/files/pmm-backup.sh` read the `pmm` UUID and row count on every ClickHouse pod through `kubectl exec` (the script's existing access path; spec C1–C2 do not apply). They are called from `backup_clickhouse`, `validate_restore_clickhouse` and `restore_clickhouse`.

**Tech Stack:** POSIX sh (dash, bash, busybox), kubectl, jq, clickhouse-client in the `clickhouse` container; the script's own unit and lint suites.

**Spec:** [`../spec.md`](../spec.md) §2.7–2.8, §4.3, §4.4, D5, D6, D10, D13; contract in [`00-roadmap.md`](00-roadmap.md).

## Global Constraints

The roadmap's global constraints apply. In addition:
- **Code base:** percona-helm-charts `main` at `ccb39dc4`; branch `PMM-15785-qan-clickhouse-db`; bump `charts/pmm-ha/Chart.yaml` to **1.8.1** (CI runs `ct lint --check-version-increment=true`).
- **Script rules** (enforced by `charts/pmm-ha/tests/pmm-backup-lint.sh`):
  - the password goes on stdin, never argv (DN-23);
  - functions whose stdout is their value log to `>&9`;
  - every SHOUTY global assigned in a function is also initialised at top level;
  - no bare `wait`;
  - every `DN-NN` reference exists in `docs/pmm-backup-design-notes.md`. The next note is **DN-52**.
- **Restore context** (from the code):
  - `restore_clickhouse` runs in a child subshell in parallel mode, so it fails the component only by returning 1;
  - restore never calls `ch_resolve_pod`/`ch_resolve_credentials` today, so the new code must;
  - `restore_verification` cannot fail a restore.
- **No new environment variable:** the cluster name comes from the `cluster` macro (`SELECT substitution FROM system.macros WHERE macro = 'cluster'`).
- **Drops only in a restore,** after PMM is stopped and the backup is downloaded, and only on pods whose UUID differs from the kept one. The restore replaces all QAN data anyway (spec §4.3, D6).

## Review Focus

1. **A restore while one ClickHouse pod has no `pmm`** (the lab's R2). Expected: `pmm` is created on that pod before the restore; afterwards there is one UUID and `count()` equals the backup's. Test: unit `restore creates pmm on a missing pod first` (Task 3) and the live R2 replay (Task 6).
2. **A restore while the restore pod holds a stray copy** (the lab's R3). Expected: the pod is recreated with the majority UUID after PMM stops; afterwards there is one UUID, no stray rows, and `count()` equals the backup's. Test: unit `restore recreates a split pod first` (Task 3) and the live R3 replay (Task 6).
3. **A ClickHouse pod down at restore time.** Expected: refused before PMM is stopped, naming the pod. Test: unit `restore preflight refuses when a pod is down` (Task 3).
4. **A backup while one pod is still copying history.** Expected: the backup runs on the pod with the most rows. Test: unit `ch_pod_most_rows returns the pod with the most rows` (Task 1).
5. **A backup during a split.** Expected: a WARN naming the UUIDs; the backup runs on the pod with the most rows. Test: unit `backup warns on a split` (Task 2).
6. **A restore from a backup made before this change** (no `metrics_rows` in the manifest). Expected: the count check is skipped with a WARN; the other checks still run. Test: unit `restore without metrics_rows only warns` (Task 4).
7. **`--dry-run` restore with a split.** Expected: it prints which pods would be dropped and recreated with which UUID, changes nothing, and exits 0. Test: unit `dry-run restore prints the fix` (Task 3).

---

### Task 1: Per-pod ClickHouse state helpers

**Files:**
- Modify:
  - `charts/pmm-ha/files/pmm-backup.sh`: new helpers next to `ch_query` (:2357-2361); `ch_query` becomes a call to `ch_query_pod "${CH_POD}" "$1"`;
  - `charts/pmm-ha/docs/pmm-backup-design-notes.md`: add `## DN-52 ClickHouse pmm database on every pod`.
- Test: `charts/pmm-ha/tests/pmm-backup-unit.sh` (new `section`s)

**Interfaces:**
- Produces:
  - `ch_pods` — prints every ClickHouse pod name, one per line, via `kubectl get pods -l "$(comp_pod_selector clickhouse)" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'` under `timeout ${KUBECTL_STATUS_TIMEOUT}`.
  - `ch_query_pod POD SQL` — `ch_query` with an explicit pod; the password on stdin as today.
  - `ch_pmm_states` — prints `POD UUID ROWS` per pod. The UUID is `-` when the pod has no `pmm` and `?` when the query fails; `ROWS` is `count()` of `pmm.metrics`, `0` without `pmm`.
  - `ch_classify` — reads `ch_pmm_states` lines on stdin and prints `VERDICT MAIN_UUID`. The verdict is one of `consistent`, `missing`, `split`, `nodb`, `unknown` (any `?`); `MAIN_UUID` is the UUID on the most pods (on a tie, the first pod's), or `-`.
  - `ch_pod_most_rows` — reads states on stdin and prints the reachable pod with the highest `ROWS`.

- [ ] **Step 1: Write failing unit sections** with `ch_query_pod` stubbed per pod:
  - `ch_classify` table: `u1 u1 u1` → `consistent u1`; `u1 u1 -` → `missing u1`; `u1 u1 u2` → `split u1`; `u1 u2 -` → `split u1`; `- - -` → `nodb -`; `u1 ? u1` → `unknown u1`.
  - `ch_pmm_states marks a failed query with ?`.
  - `ch_pod_most_rows returns the pod with the most rows`: rows 900, 1000, 400 → the second pod.
- [ ] **Step 2: Run** `make test-pmm-backup` → FAIL (undefined functions).
- [ ] **Step 3: Implement** the helpers and DN-52, which explains:
  - why every pod is checked, and why a backup uses the pod with the most rows (a recreated pod copies its history in the background);
  - why a restore may drop and recreate `pmm` on a pod (it replaces QAN data anyway; lab R3);
  - why no new environment variable is needed (the `cluster` macro).
- [ ] **Step 4: Run** `make test-pmm-backup` → PASS (the lint runs first), then the same under dash and busybox as CI does (`.github/workflows/pmm-ha-pr-checks.yaml:64-72`).
- [ ] **Step 5: Commit** `PMM-15785 Read the pmm database state on every ClickHouse pod`.

---

### Task 2: Backup pod choice and manifest fields

**Files:**
- Modify: `charts/pmm-ha/files/pmm-backup.sh`:
  - `backup_clickhouse`: after `ch_has_backup_api` at :2471, and before the dry-run block at :2477;
  - `ch_record_result` at :2592-2601;
  - `load_manifest` at :2015-2016: new `MF_CH_PMM_UUID` and `MF_CH_METRICS_ROWS`, initialised at top level next to :281-283.
- Test: `charts/pmm-ha/tests/pmm-backup-unit.sh`

**Interfaces:**
- Consumes: Task 1.
- Produces: manifest fields `components.clickhouse.pmm_uuid` and `components.clickhouse.metrics_rows`.
  - `metrics_rows` is the sum of the `count.txt` files of the frozen `pmm.metrics` parts in the local backup, read in the `clickhouse-backup` container after `create` and before `upload`/`delete local`.
  - Not `system.parts`: a part replaced by a merge leaves it after `old_parts_lifetime` (480 s, the default), so a later lookup undercounts.

- [ ] **Step 1: Find the frozen parts.** In the lab, after `create`, run `kubectl exec <ch pod> -c clickhouse-backup -- find /var/lib/clickhouse/backup/<name>/shadow -name count.txt` and confirm which paths belong to `pmm.metrics`. Record the path pattern in DN-52.
- [ ] **Step 2: Write failing unit sections:**
  - `backup uses the pod with the most rows`: rows 900, 1000, 400 → `CH_POD` is the second pod.
  - `backup warns on a missing or unreachable pod`: `- u1 u1` and `? u1 u1` → proceeds, with a WARN naming the pod.
  - `backup warns on a split`: `u1 u1 u2` → proceeds on the pod with the most rows, with a WARN naming both UUIDs.
  - `backup refuses without pmm anywhere`: `- - -` → returns 1.
  - `the manifest records pmm_uuid and metrics_rows` (stubbed `result_set`).
- [ ] **Step 3: Run** `make test-pmm-backup` → FAIL.
- [ ] **Step 4: Implement.** `CH_POD` comes from `ch_pod_most_rows` instead of `.items[0]`.
- [ ] **Step 5: Run** → PASS (dash, bash, busybox).
- [ ] **Step 6: Commit** `PMM-15785 Back up QAN data from the most complete ClickHouse pod`.

---

### Task 3: Restore preflight and one `pmm` before restore

**Files:**
- Modify: `charts/pmm-ha/files/pmm-backup.sh`:
  - `validate_restore_clickhouse` at :3414 (preflight; PMM still up);
  - `restore_clickhouse` at :3992-4018 (PMM scaled down).
- Test: `charts/pmm-ha/tests/pmm-backup-unit.sh`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `ch_cluster_healthy` — returns 1 with the reason unless every ClickHouse pod is Running and answers `SELECT 1`, `system.zookeeper` is readable, and there is one shard.
  - `ch_heal_pod TARGET HEALTHY UUID` — the roadmap's SQL contract, in order:
    1. read `shard` and `replica` from `system.macros` on TARGET;
    2. on HEALTHY, if `/clickhouse/databases/UUID/replicas` lists `shard|replica` (`system.zookeeper`), run `SYSTEM DROP DATABASE REPLICA`;
    3. on HEALTHY, for each table of `pmm` whose Keeper path lists `replica`, run `SYSTEM DROP REPLICA … FROM TABLE pmm.<t>`;
    4. on TARGET, run the per-node `CREATE … UUID`;
    5. poll TARGET's `system.tables` until it has HEALTHY's tables (timeout 120 s).
  - `ch_create_pmm_on_cluster` — for `nodb`: UUID from `/proc/sys/kernel/random/uuid`, cluster from the `cluster` macro, the `ON CLUSTER` create, run on the first pod.
  - `ch_one_pmm` — keeps `ch_classify`'s main UUID. For each pod with another UUID: `DROP DATABASE pmm SYNC`, then `ch_heal_pod`. For each pod without `pmm`: `ch_heal_pod`. With no UUID anywhere: `ch_create_pmm_on_cluster`. With `DRY_RUN=true` it only prints these actions.

- [ ] **Step 1: Write failing unit sections:**
  - `restore preflight refuses when a pod is down`: one pod not Running → `validate_restore_clickhouse` returns 1 naming it, and nothing is scaled.
  - `restore recreates a split pod first`: states `u2 u1 u1` → `DROP DATABASE pmm SYNC` and `ch_heal_pod` with `u1` run on the first pod before `clickhouse-backup restore`.
  - `restore keeps the first pod's UUID on a tie`: `u1 u2 -` → the second pod is recreated and the third healed, both with `u1`.
  - `restore creates pmm on a missing pod first`: `u1 u1 -` → `ch_heal_pod` for the third pod with `u1` before `clickhouse-backup restore`.
  - `restore creates pmm when no pod has it`: `- - -` → `ch_create_pmm_on_cluster` is called.
  - `ch_heal_pod runs the Keeper cleanup only when registered`: stub `system.zookeeper` empty vs listed → zero vs two `SYSTEM DROP` statements.
  - `dry-run restore prints the fix`: `u2 u1 u1` with `DRY_RUN=true` → the planned drop and create are printed, no statement runs, return 0.
  - `restore downloads before changing pmm`: the stubbed `download` fails → `ch_one_pmm` never runs and the restore returns 1.
- [ ] **Step 2: Run** `make test-pmm-backup` → FAIL.
- [ ] **Step 3: Implement.** Each function calls `ch_resolve_credentials` first. `restore_clickhouse` no longer uses `.items[0]` (:3994):
  - with the `s3` target: `clickhouse-backup download`, then `ch_one_pmm`, then `clickhouse-backup restore --rm` and `delete local`, in one pod with the kept UUID;
  - with `shared`: the existing `pod_sh` call is split in two, the untar into the local backup directory first, then `ch_one_pmm`, then `clickhouse-backup restore --rm`.

  Either way, a failed download or untar changes nothing.
- [ ] **Step 4: Run** → PASS (dash, bash, busybox).
- [ ] **Step 5: Commit** `PMM-15785 Bring ClickHouse to one pmm database before a restore`.

---

### Task 4: Verify ClickHouse after a restore

**Files:**
- Modify: `charts/pmm-ha/files/pmm-backup.sh`, `restore_clickhouse`: after the restore's rc check and the dry-run return, before `log "INFO" "[ClickHouse] Restore complete"` (:4015-4018).
- Test: `charts/pmm-ha/tests/pmm-backup-unit.sh`

**Interfaces:**
- Produces: `ch_verify_restore EXPECTED_ROWS` — returns 0 only when all of these hold:
  - `ch_classify` is `consistent`;
  - every pod reports the same table UUIDs (`SELECT name, uuid FROM system.tables WHERE database = 'pmm'`);
  - every pod's `count()` is equal, polled every 10 s; the check fails only when no pod's count changed for 10 min, because a single `SYSTEM SYNC REPLICA` can outlast the client's 300 s `receive_timeout` on a large restore [I];
  - and, when `EXPECTED_ROWS` is not empty, that count equals `EXPECTED_ROWS`.

  On failure it logs one ERROR line with the failing check and the per-pod values, and `restore_clickhouse` returns 1. `CLICKHOUSE_OK` stays false, so PMM stays at 0 replicas and the run exits 1 (:5829-5832).

- [ ] **Step 1: Write failing unit sections:**
  - `restore verify passes when consistent and counts match`.
  - `restore verify fails on two UUIDs` (the R2 outcome).
  - `restore verify fails when count differs from metrics_rows`.
  - `restore without metrics_rows only warns`: empty `EXPECTED_ROWS` → returns 0 with a WARN.
  - `a failed verify keeps PMM down`: `cmd_restore` with stubbed components → `scale_up_pmm` is not called and the exit code is 1.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS (dash, bash, busybox).
- [ ] **Step 5: Commit** `PMM-15785 Fail a restore that leaves ClickHouse inconsistent`.

---

### Task 5: Chart version and docs

**Files:**
- Modify:
  - `charts/pmm-ha/Chart.yaml:5` → `1.8.1`;
  - `charts/pmm-ha/docs/pmm-backup.md`: the ClickHouse sections at :442 and :1820-1838, Restore Flow steps 9–11 at :1909-1959, Troubleshooting at :1650, Known Limitations at :2096.

- [ ] **Step 1: Docs.**
  - `pmm-backup.md`: the backup pod choice; how a restore brings ClickHouse to one `pmm` and refuses while a pod is down; the restore failure with PMM left down.
  - Troubleshooting: "Restore refused: a ClickHouse pod does not answer".
  - Known Limitations: add that a restore needs every ClickHouse pod up.
- [ ] **Step 2: Run** `make test-pmm-backup`, `make test-pmm-ha`, and `ct lint` as in `pmm-ha-pr-checks.yaml:202` → PASS.
- [ ] **Step 3: Commit** `PMM-15785 Document ClickHouse handling in pmm-backup.sh`.

---

### Task 6: Live replay of the lab cases

**Files:** none (results go into the PR description).

- [ ] **Step 1:** Install this chart branch with S3 backups (as in the lab: SeaweedFS, `centralBackupStorage.mode: s3`), and run `pmm-backup.sh backup`. `list <id>` shows the manifest with `pmm_uuid` and `metrics_rows`.
- [ ] **Step 2: R1.** Restore in place → exit 0. One UUID; `count()` equals `metrics_rows`.
- [ ] **Step 3: R2.** `DROP DATABASE pmm SYNC` on the first ClickHouse pod, then restore → the log shows the create, exit 0, one UUID, `count()` equals `metrics_rows`. Before this change: split and no rollback.
- [ ] **Step 4: R3.** Create a stray copy on the first ClickHouse pod (plan 01 Task 6 Step 5's procedure), then restore → the log shows the recreate, exit 0, one UUID, no stray rows, `count()` equals `metrics_rows`. Use the released PMM image, which does not fix splits, so the split stays until the restore.
