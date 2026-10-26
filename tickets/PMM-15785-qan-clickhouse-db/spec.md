# QAN database consistency across ClickHouse replicas (PMM-15785)

- **Ticket:** [PMM-15785](https://perconadev.atlassian.net/browse/PMM-15785), under epic [PMM-14381](https://perconadev.atlassian.net/browse/PMM-14381).
- **Code base:** percona/pmm `main` at `8540e366a`, percona/percona-helm-charts `main` at `ccb39dc4` (pmm-ha 1.8.0, PMM 3.10.0). Line numbers refer to those commits; re-check them before you edit.
- **Lab:** 3-node k3s, pmm-ha 1.8.0 with the chart's ClickHouse defaults (1 shard, 3 replicas, ClickHouse 25.8.28, clickhouse-backup 2.8.0), S3 backups to an in-cluster SeaweedFS, 2026-10-23 to 2026-10-26.

Marks used below:
- **[V]** verified in the code or in the lab.
- **[I]** inferred, or taken from upstream documentation, and not run.

---

## 1. Summary

PMM HA keeps QAN data in a ClickHouse `Replicated` database named `pmm`. The replicas form one group only when every replica has `pmm` with the same UUID. ClickHouse then replicates everything on its own; it only never creates `pmm` on a replica that lacks it. Today:

- an install-time race leaves one replica without `pmm` (1 of 5 lab installs);
- a qan-api2 start against that replica creates `pmm` again with a new UUID, so that replica holds a separate copy (a **split**), and QAN shows whichever copy the leader happens to use;
- a node that loses its volume stays without `pmm`;
- a `pmm-backup.sh` restore on a replica without `pmm` creates a split too, and ClickHouse is silently not rolled back.

**What gets built:**

1. **Fix the race (qan-api2).** `pmm` is created only after the replica in use lists every node, always with an explicit UUID that reuses an existing one.
2. **Keep every node on one `pmm` (qan-api2, HA leader only, at start and every 10 min).** A node without `pmm` gets it with the existing UUID. If nodes hold different copies, the copy with the most rows is kept and `pmm` is dropped and recreated on the other nodes. On installs that are already split, this happens once, in the first pass after the upgrade. Rows that exist only in a dropped copy are lost.
3. **Backup** runs on the pod with the most rows.
4. **Restore** checks the cluster, brings every node to one `pmm` (dropping and recreating it where needed), then restores and verifies.
5. **Automated tests** in the HA test suites.

**Decisions:** [§7](#7-decisions).

---

## 2. How the problem happens [V]

1. The Altinity operator adds replicas one by one and rewrites `remote_servers` after each. Every replica picks up the new file at its own moment. In 5 of 5 lab installs there was a window of 30–60 s in which the newest replica listed all 3 hosts and the older ones listed 2.
2. The chart's `wait-for-clickhouse` init container (`charts/pmm-ha/templates/statefulset.yaml:94-106`) waits for 3 rows in `system.clusters`, but asks whichever replica the Service picks.
3. qan-api2 checks only that there is at least one remote host (`qan-api2/migrations/migrations.go:28-60`). It connects to `pmm` through `pmm-ha-clickhouse-sticky` (ClientIP affinity, 3 h). On `UNKNOWN_DATABASE` it runs (`qan-api2/db.go:76,133-134`):

   ```sql
   CREATE DATABASE IF NOT EXISTS pmm ON CLUSTER "pmmdb" ENGINE = Replicated('/clickhouse/databases/{uuid}', '{shard}', '{replica}')
   ```

   The DDL reaches only the hosts the receiving replica lists, so the last-added replica can end up without `pmm`.
4. qan-api2 runs on every PMM replica, and each PMM pod sticks to one random ClickHouse replica; a pod with a new IP picks again. A qan-api2 that starts against the replica without `pmm` runs the same DDL. There is no UUID in it, so that replica gets its own `pmm`. The tables qan-api2 then creates use `{uuid}` paths, so the data diverges too.
5. QAN reads and writes go through the leader's qan-api2, so the UI shows whichever copy the leader's connection points to. With the leader on the stray replica, `/v1/qan/metrics:getReport` returned only its rows: 1,463 queries against 12,231 on the other replicas for the same hour.
6. **Writes move without a restart.** A stray copy on one replica started receiving all of the leader's QAN writes at 18:00, although no PMM pod had restarted since the previous day. From 18:00 to 21:48 the other copy got no QAN rows and the stray got 27,454. Inferred cause: the Service's ClientIP affinity expired after 3 h without new connections from the leader, and its next connection landed on the stray replica [I].
7. **`pmm-backup.sh` restore** runs `clickhouse-backup restore_remote --rm` on one pod (`items[0]`, `restore_clickhouse` in `charts/pmm-ha/files/pmm-backup.sh:3992`). clickhouse-backup runs `CREATE DATABASE IF NOT EXISTS pmm ENGINE=Replicated(...)` without a UUID, then drops and recreates the tables with the Keeper paths stored in the backup, then attaches parts.
   - When that pod has `pmm` (lab R1), the CREATE is a no-op and the table DDL replicates through the database log: consistent.
   - When it has no `pmm` (lab R2), it creates a new `pmm` there. The tables use the backup's explicit Keeper paths, so data stays shared, but the database metadata is split. In R2, ClickHouse was **not** rolled back to the backup (row count 2,142,635 before, 2,142,952 after, carrying on from live data). The run still exited 0, with "ClickHouse: ✓ Yes" and "Restore completed successfully" in its summary.
8. **Backup** also runs on `items[0]` (`ch_resolve_pod`). Not tested: a backup from a pod without `pmm`, or from the stray side of a split, would hold no QAN data or one copy only [I].

---

## 3. Constraints found in the lab

| # | Constraint | Consequence |
|---|---|---|
| C1 | `pmm-hardening.xml` sets an empty `<remote_url_allow_hosts>`; `remote()` fails with `UNACCEPTABLE_URL` [V]. | No cross-node queries with `remote()`. |
| C2 | `cluster()`/`clusterAllReplicas()` fail with `default: Authentication failed`; the cluster definition authenticates as `default` [V]. | qan-api2 inspects each node over a **direct client connection** with the PMM ClickHouse user. |
| C3 | The PMM container has `PMM_CLICKHOUSE_NODES` (every replica's FQDN, from `shards × replicas`, `_helpers.tpl:266-274`) and `PMM_CLICKHOUSE_USER/PASSWORD/CLUSTER_NAME` [V]. qan-api2 is expected to inherit them through supervisord, as pmm-managed does [I]. | Node list and credentials for direct connections; no new chart variable. |
| C4 | Both tables in `pmm` (`metrics`, `schema_migrations`) are `ReplicatedMergeTree`. A node that gets `pmm` with the existing UUID receives both tables within seconds, then copies the full history, rows written meanwhile and schema changes in the background; partitions dropped by retention stay dropped [V]. | Fixing a node is one `CREATE`; ClickHouse does the rest. |
| C5 | Only the leader's qan-api2 writes rows (HAProxy sends client traffic to the leader); qan-api2 has no leader awareness today [V]. | The leader's connection decides which copy QAN writes to; after an upgrade that is a new, effectively random node, so the writer is not used to pick the kept copy. |
| C6 | Inside a PMM pod, `GET http://127.0.0.1:7772/v1/ha/nodes` answers without credentials with every node's role and `status` (`alive`) plus `expected_nodes`, and `PMM_HA_NODE_ID` holds the pod's node name [V]. | qan-api2 can tell whether it runs on the HA leader, and whether that leader sees every PMM node (not a split brain, for which PMM ships the `ha_split_brain` alert). |
| C7 | After a volume loss, the operator creates nothing on the rebuilt node, and Keeper still lists the node under `pmm` and under each table. A plain `CREATE` fails with `REPLICA_ALREADY_EXISTS` [V]. | Stale registrations are removed before the `CREATE` (§4.2). |
| C8 | After a restore, table engines carry explicit Keeper paths from the backup, so two `pmm` copies can share their tables' data. `DROP DATABASE pmm SYNC` plus `CREATE … UUID '<other>'` on one node then re-homed it with identical rows on all nodes [V]. | Dropping a copy whose tables share the kept copy's paths loses nothing. |
| C9 | ClickHouse replica macros: `shard` is `0`, `replica` is `chi-<release>-<cluster>-0-<n>`; Keeper names a database replica `<shard>\|<replica>` [V]. | Read `system.macros` on the target node; `system.clusters.shard_num` is 1-based and not the macro. |
| C10 | `hostName()` returns the ClickHouse pod name (`pmm-ha-pmmdb-0-0-0`), not the `replica` macro (`chi-pmm-ha-pmmdb-0-0`) [V]. | Nodes are identified with `getMacro('replica')`. |
| C11 | `UUID` must come before `ON CLUSTER`: `CREATE DATABASE … ON CLUSTER … UUID '…'` fails with a syntax error (code 62), `CREATE DATABASE … UUID '…' ON CLUSTER …` gives one UUID on all nodes [V]. Two concurrent `ON CLUSTER` creates with different explicit UUIDs ended with one UUID on all three nodes in 3 of 3 runs [V, PR review]. | The statement order is fixed in the contract; concurrent first creations are safe. |
| C12 | The operator's statement for a new replica, `CREATE DATABASE IF NOT EXISTS "pmm" Engine = <engine_full>`, keeps `{uuid}` and creates no tables in a Replicated database: replayed on 25.8.28 it gave the replica its own UUID and no `metrics` table, so `count()` failed with `UNKNOWN_TABLE` (code 60) [V, PR review]. | A `pmm` without `metrics` counts as 0 rows, not as an unreachable node. |

---

## 4. Design

### 4.1 Fix the race: create `pmm` safely (qan-api2 `db.go`, `migrations.go`)

On a connection to `pmm` that fails with `UNKNOWN_DATABASE`:

1. **Complete view.** Run the cluster check and the DDL on one pinned connection. Proceed only when that replica's `system.clusters` lists every host in `PMM_CLICKHOUSE_NODES` for `PMM_CLICKHOUSE_CLUSTER_NAME`.
2. **Find the UUID.** Read `uuid` from `system.databases WHERE name = 'pmm'` on every node over direct connections.
   - None found: generate one and create `pmm` `ON CLUSTER` with it (C11). Two pods starting together still end with one UUID.
   - One found: create `pmm` with it on the nodes that lack it and that Keeper does not list; a node with a stale registration is left to §4.2.
   - More than one found: create nothing and retry as in step 3; §4.2 fixes the split.
3. **If the node behind qan-api2's connection still has no `pmm`** (it was skipped above), qan-api2 does not exit: it retries every few seconds. The §4.2 routine runs independently of this connection, so in the leader it fixes that node and the retry then succeeds. Exiting instead would restart qan-api2 onto the same node every time (the Service's ClientIP affinity), and nothing would ever fix it.
4. **Without `PMM_CLICKHOUSE_NODES`** (non-chart deployments with `PMM_CLICKHOUSE_IS_CLUSTER=1`), keep today's behaviour but pass an explicit UUID.

qan-api2 never generates a UUID while any node has `pmm`.

### 4.2 Keep every node on one `pmm` (qan-api2, HA leader only)

The qan-api2 of the PMM HA leader (C6) runs this at start, before and independently of its own connection to `pmm`, and then every 10 minutes; the others skip it, so two pods never change the same node. It reads the `pmm` UUID on every node over direct connections, then:

- **All nodes agree:** nothing to do.
- **Some nodes have no `pmm`:** on each, remove any stale Keeper registration (`SYSTEM DROP DATABASE REPLICA` and `SYSTEM DROP REPLICA` per table, run on a healthy node, C7), then `CREATE DATABASE IF NOT EXISTS pmm UUID '<existing>'`. ClickHouse copies the tables and rows in the background (C4).
- **Nodes hold different UUIDs (a split):** keep the copy with the most rows (`count()` of `pmm.metrics`; a `pmm` without that table counts as 0, C12), then the lowest UUID. On every node with another UUID:
  - check leadership again, and drop only while the leader sees every expected PMM node alive (C6), so two leaders in a split brain never drop each other's copy;
  - read the kept UUID again on a node that holds it;
  - `DROP DATABASE pmm SYNC`, then the create as for a node without `pmm`.
- **A node does not answer** (the connection fails; a missing table is not that): skip it this pass. In a split, change nothing until every node answers, because the missing node may hold the larger copy.
- **More than one shard:** change nothing and log it.

Each action is logged at warning level with the node, the old and new UUID, and the dropped copy's row count.

**Data loss, accepted (D2).** Rows that exist only in a dropped copy are gone: up to the whole history of the other copy. A copy whose tables share the kept copy's Keeper paths (made by a restore, C8) loses nothing.

**Once after the upgrade.** On an install that is already split, the first pass after the upgrade fixes it; afterwards §4.1 prevents new splits, and passes only act on a node that lost `pmm`. The copy with the most rows is normally the one with the full history; a stray made by the race holds only what was written to it.

**Visibility:** the log lines. No metrics, alert or dashboard panel (D7).

### 4.3 Backup and restore (`charts/pmm-ha/files/pmm-backup.sh`)

1. **Per-pod check** used by `backup` and `restore`: read the `pmm` UUID and `count()` on every ClickHouse pod through `kubectl exec`; C1–C2 do not apply to this path.
2. **Backup:** run `clickhouse-backup create` on the pod with the most rows, not blindly on `items[0]` (`ch_resolve_pod`). A pod that was just recreated, or was down, may still be copying history; the pod with the most rows is the most complete. If the pods report different UUIDs, log a warning and continue.
3. **Restore, before ClickHouse.** A restore replaces all QAN data with the backup's, so it fixes any state first:
   - **Preflight, while PMM is up:** refuse if a ClickHouse or Keeper pod does not answer. Its UUID is unknown, and it could come back holding another copy.
   - **After PMM is stopped and the backup is downloaded** (so a failed download changes nothing): keep the UUID on the most pods (on a tie, the first pod's). On pods with another UUID, `DROP DATABASE pmm SYNC`. On those and on pods without `pmm`, the §4.2 create with the kept UUID, waiting for the tables but not for rows. With no `pmm` anywhere, create it `ON CLUSTER` with a new UUID.
   - Then run `clickhouse-backup restore --rm` on any pod. Every pod now shares one `pmm`, so the restore reaches every pod through the database (lab R1).

   **[V] lab R3:** a stray copy sat on the restore pod (`items[0]`). The fix re-homed it in about 10 s; the restore then left one UUID and identical table UUIDs on every pod, rows older than the backup matched it exactly, and the stray rows and the rows written after the backup were gone.
4. **Restore, after ClickHouse:** verify one `pmm` UUID and the same table UUIDs on every pod, and equal row counts (polled while they still grow). On any mismatch, exit non-zero, mark the restore failed and leave PMM down.

### 4.4 Chart (percona-helm-charts)

- `pmm-backup.sh` changes of §4.3, with their docs (`charts/pmm-ha/docs/pmm-backup.md`); chart version 1.8.1.
- `wait-for-clickhouse` stays as it is: §4.1 closes the race on its own.
- **Operator:** after a volume loss it creates nothing (C7); §4.2 handles that node. When replicas are added, the operator gives the new replica `pmm` with its own UUID and no tables (C12). §4.2 counts that copy as 0 rows and recreates it with the kept UUID [I: not run end to end].

### 4.5 Scenarios

| Scenario | Fixed by | Test |
|---|---|---|
| Install race | §4.1 | T1 |
| A node without `pmm` (manual drop, volume loss) | §4.2 create, with Keeper cleanup after a volume loss | T2, T3 |
| Existing split, QAN writing to the main copy | §4.2: the copy with the most rows kept; the stray node recreated | T4 |
| Existing split, QAN writing to the stray | §4.2: the same; which copy QAN writes to does not matter | T5 |
| Split made by a pre-fix restore (shared table paths) | §4.2, nothing lost | T6 |
| Backup while a node is still copying | §4.3: the pod with the most rows | plan 02 unit test |
| Restore with a node without `pmm` or a split | §4.3 | T8 |
| A `pmm` without tables (crash after `CREATE`, interrupted restore, replica added by the operator) | §4.2: 0 rows, recreated | plan 01 cluster test |
| qan-api2's own node lost its volume | §4.1 step 3: retry; §4.2 fixes the node | T3 |
| Split brain (two PMM leaders) | §4.2: no drop without a full view | plan 01 unit test |

---

## 5. Goals, non-goals, anti-goals

- **Goals:**
  - No new install ends with a node missing `pmm` or with two UUIDs.
  - Existing splits and nodes without `pmm` are fixed without customer action.
  - Backups capture the most complete copy, and restores either restore it on every node or fail loudly.
- **Non-goals:**
  - keeping rows that exist only in a dropped copy (D2);
  - an alert or dashboard panel (D7);
  - multi-shard layouts; deployments without `PMM_CLICKHOUSE_NODES`.
- **Anti-goals:**
  - qan-api2 generating a UUID while a node has `pmm`;
  - two pods dropping or creating `pmm` at the same time;
  - a restore that reports success while ClickHouse is inconsistent or not restored.

---

## 6. Testing

**Unit:** UUID decisions (§4.1), the kept-copy rule and the leader check (§4.2), and the `pmm-backup.sh` per-pod check, pod choice and restore fix.

**Automated HA tests (D8):**

| # | Case | Pass |
|---|---|---|
| T1 | Fresh install, repeated (at least 5) | one UUID on every node, every time |
| T2 | `DROP DATABASE pmm SYNC` on a node | recreated with the same UUID within one interval; row counts and checksums equal |
| T3 | Delete one ClickHouse node's PVC and pod; then the same for the node the leader's qan-api2 uses, restarting that qan-api2 | recreated, including the stale Keeper registrations; counts equal; qan-api2 retries instead of crash-looping and QAN answers again |
| T4 | Split: a small stray copy on a node QAN does not write to | the stray node recreated with the main UUID; the main copy's rows unchanged |
| T5 | Split: a small stray copy on the node QAN writes to | the main UUID kept on every node (more rows); the main copy's rows unchanged |
| T6 | Split with shared table paths (the state a pre-fix restore leaves, R2) | one UUID; counts and checksums unchanged |
| T7 | `pmm-backup.sh backup`, then `restore` in place | one UUID; equal counts on every pod; rows written after the backup are gone |
| T8 | Split, and separately a missing `pmm`, on the first ClickHouse pod; then `restore`. Also with no `pmm` on any pod | fixed before restoring; one UUID; equal counts on every pod; no stray rows |
| T9 | Restore into a fresh install (another namespace) | one UUID; equal counts on every pod |

**Docs:** `pmm-backup.md`; the PMM HA troubleshooting docs (how to check the UUID per node, what the log lines mean); release note.

---

## 7. Decisions

| # | Decision | By |
|---|---|---|
| D1 | Fix the race in qan-api2: `pmm` is created with an explicit UUID that reuses an existing one, and only with a complete cluster view. | ticket owner |
| D2 | Existing splits are fixed by keeping the copy with the most rows and dropping and recreating `pmm` on the other nodes. Rows only in a dropped copy are lost (2026-10-26; replaces the earlier merge design, and "the copy QAN writes to", which after an upgrade is a random node). | ticket owner |
| D3 | Only the HA leader's qan-api2 creates, drops or recreates `pmm`; it drops only while it sees every expected PMM node alive. | ticket owner |
| D4 | A node without `pmm` gets it back automatically. | ticket owner |
| D5 | A backup runs on the pod with the most rows. | ticket owner |
| D6 | A restore checks the cluster, brings every node to one `pmm` (drop and recreate where needed), then restores. | ticket owner |
| D7 | No metrics, alert or dashboard panel; log lines only (2026-10-26). | ticket owner |
| D14 | Keep the solution as simple as possible: a split at startup is retried until the leader fixes it; the backup manifest records no row count; no interface or fake in the Go code (2026-10-26). | ticket owner |
| D8 | The test cases in §6 become automated HA tests. | ticket owner |
| D9 | qan-api2 inspects each node over direct connections from `PMM_CLICKHOUSE_NODES` (C1–C3). | author |
| D10 | Stale Keeper registrations are removed before `pmm` is created on a node (C7). | author |
| D11 | The first creation uses `ON CLUSTER` with an explicit UUID; later creations are per node. | author |
| D12 | §4.2 runs at start and every 10 minutes, so an existing split is fixed in the first pass after the upgrade. | author |
| D13 | A restore refuses when a ClickHouse or Keeper pod does not answer. | author |

## 8. Left to the builder

- The interval and the log wording.
