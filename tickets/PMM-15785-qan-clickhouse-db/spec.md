# QAN database consistency across ClickHouse replicas (PMM-15785)

- **Ticket:** [PMM-15785](https://perconadev.atlassian.net/browse/PMM-15785), under epic [PMM-14381](https://perconadev.atlassian.net/browse/PMM-14381).
- **Code base:** percona/pmm `main` at `8540e366a`, percona/percona-helm-charts `main` at `ccb39dc4` (pmm-ha 1.8.0, PMM 3.10.0). Line numbers refer to those commits; re-check them before you edit.
- **Lab:** 3-node k3s, pmm-ha 1.8.0 with the chart's ClickHouse defaults (1 shard, 3 replicas, clickhouse-backup 2.8.0), S3 backups to an in-cluster SeaweedFS, 2026-10-23/24.

Marks used below:
- **[V]** verified in the code or in the lab.
- **[I]** inferred, or taken from upstream documentation, and not run.

---

## 1. Summary

PMM HA keeps QAN data in a ClickHouse `Replicated` database named `pmm`. The replicas form one group only when every replica has `pmm` with the same UUID. Three things break that today:

- an install-time race leaves one replica without `pmm` (1 of 5 lab installs);
- a qan-api2 start against that replica creates `pmm` again with a new UUID, so that replica holds a separate copy, and QAN shows whichever copy the leader's connection points to;
- a `pmm-backup.sh` restore run on a replica without `pmm` does the same, and ClickHouse is then silently not rolled back.

**What gets built:**

1. **Prevent (qan-api2).** `pmm` is created only after the replica in use lists every node, always with an explicit UUID that reuses an existing one.
2. **Heal (qan-api2, automatic).** Creates `pmm` with the existing UUID on any replica that has no `pmm`, cleaning up stale Keeper registrations if needed. It never drops or loses data.
3. **Flag (qan-api2 metric, alert, dashboard panel).** A split is reported, never changed automatically.
4. **Repair (command run by the customer).** It is a dry run by default and acts only with `--apply`. It handles both kinds of split (§4.4).
5. **Backup and restore (`pmm-backup.sh`).** Checks consistency before and after, runs on a replica that has `pmm`, and refuses a split.
6. **Automated tests** for all of the above in the HA test suites.

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
4. qan-api2 runs on every PMM replica, and each PMM pod sticks to one random ClickHouse replica; a pod with a new IP picks again. A qan-api2 that starts against the replica without `pmm` runs the same DDL. There is no UUID in it, so that replica gets its own `pmm`. The tables qan-api2 then creates use `{uuid}` paths, so the data diverges too (**split S1**).
5. With the leader's connection on the stray replica, `/v1/qan/metrics:getReport` returned only its rows: 1,463 queries against 12,231 on the other replicas for the same hour.
6. **`pmm-backup.sh` restore** runs `clickhouse-backup restore_remote --rm` on one pod (`items[0]`, `restore_clickhouse` in `charts/pmm-ha/files/pmm-backup.sh:3992`). clickhouse-backup runs `CREATE DATABASE IF NOT EXISTS pmm ENGINE=Replicated(...)` without a UUID, then drops and recreates the tables with the Keeper paths stored in the backup, then attaches parts.
   - When that pod has `pmm` (lab R1), the CREATE is a no-op and the table DDL replicates through the database log: consistent.
   - When it has no `pmm` (lab R2), it creates a new `pmm` there. The tables use the backup's explicit Keeper paths, so data stays shared, but the database metadata is split (**split S2**). In R2, ClickHouse was **not** rolled back to the backup (row count 2,142,635 before, 2,142,952 after, carrying on from live data). The run still exited 0, with "ClickHouse: ✓ Yes" and "Restore completed successfully" in its summary.
7. **Backup** also runs on `items[0]` (`ch_resolve_pod`). Not tested: a backup from a pod without `pmm`, or from one side of an S1 split, would hold no QAN data or one copy only [I].

An install that comes up with one UUID on every replica stays consistent until something removes `pmm` from a replica (volume loss, §4.2) or a restore runs on such a replica.

---

## 3. Constraints found in the lab

| # | Constraint | Consequence |
|---|---|---|
| C1 | `pmm-hardening.xml` sets an empty `<remote_url_allow_hosts>`; `remote()` fails with `UNACCEPTABLE_URL` [V]. | No server-side copy between replicas. |
| C2 | `cluster()`/`clusterAllReplicas()` fail with `default: Authentication failed`; the cluster definition authenticates as `default` [V]. | Use **direct client connections** to each replica with the PMM ClickHouse user. |
| C3 | The PMM container has `PMM_CLICKHOUSE_NODES` (every replica's FQDN, from `shards × replicas`, `_helpers.tpl:266-274`) and `PMM_CLICKHOUSE_USER/PASSWORD/CLUSTER_NAME` [V]. qan-api2 is expected to inherit them through supervisord, as pmm-managed does [I]. | Node list and credentials for direct connections; no new chart variable. |
| C4 | `pmm.metrics` has 269 columns; a 200k-row Native insert hit the 2.7 GiB memory limit of the lab sizing, 5k-row batches worked [V]. | Copies stream in bounded batches. |
| C5 | A stray copy can have an older schema (it lacked a column the main copy had) [V]. | Copy by the stray table's column names. |
| C6 | Both tables in `pmm` (`metrics`, `schema_migrations`) are `ReplicatedMergeTree` [V]. | Recreating `pmm` with the main UUID rebuilds both from Keeper and fetches all data. |
| C7 | Only the leader's qan-api2 writes rows (HAProxy sends client traffic to the leader); qan-api2 has no leader awareness [V]. | The heal must be safe from every pod at once. |
| C8 | qan-api2's `/debug/metrics` (port 9933) is scraped as job `qan-api2` from every PMM pod in HA [V]. | The split metric can come from qan-api2. |
| C9 | After a volume loss, Keeper still lists the node under `pmm` and under each table. A plain `CREATE` fails with `REPLICA_ALREADY_EXISTS` [V]. | The heal removes stale registrations first (§4.2). |
| C10 | After a restore, table engines carry explicit Keeper paths from the backup (`/clickhouse/tables/<backup-time table uuid>/{shard}`) [V]. | Whether two `pmm` copies share data has to be checked per table, not assumed (S1 vs S2). |

---

## 4. Design

### 4.1 Prevent: create `pmm` safely (qan-api2 `db.go`, `migrations.go`)

On a connection to `pmm` that fails with `UNKNOWN_DATABASE`:

1. **Complete view.** Run the cluster check and the DDL on one pinned connection. Proceed only when that replica's `system.clusters` lists every host in `PMM_CLICKHOUSE_NODES` for `PMM_CLICKHOUSE_CLUSTER_NAME`.
2. **Find the UUID.** Read `uuid` from `system.databases WHERE name = 'pmm'` on every node over direct connections.
   - None found: generate one.
   - Exactly one found: use it.
   - More than one found: create nothing, log the split, set the metric (§4.3), and fail as today. qan-api2 never creates a third UUID.
3. **Create, then verify all nodes.**
   - No node has `pmm`: `CREATE DATABASE IF NOT EXISTS pmm ON CLUSTER "<cluster>" UUID '<u>' ENGINE = Replicated(...)`. Two pods starting together could each pick a UUID. The cluster DDL queue applies their statements in one order on every node, so the second is a no-op everywhere. Per-node creation could leave different UUIDs.
   - A UUID exists: create per node with it, as in §4.2.
4. **Without `PMM_CLICKHOUSE_NODES`** (non-chart deployments with `PMM_CLICKHOUSE_IS_CLUSTER=1`), keep today's behaviour but pass an explicit UUID.

### 4.2 Heal: node without `pmm` (qan-api2, automatic)

A routine runs at qan-api2 start (after §4.1) and then periodically; the author suggests every 10 min. It reads the `pmm` UUID on every node over direct connections.

**Rule:** the heal never drops a database, never deletes rows, and never touches a node that has a `pmm` database. It acts only on a node that is reachable **and** has no `pmm`. Such a node holds no QAN data locally. Data that existed only on a lost disk is already gone, and the heal cannot make that worse.

| Found | Action |
|---|---|
| One UUID on all nodes | nothing |
| One UUID; some reachable nodes without `pmm` | heal each (below); log; count in a metric |
| Two or more UUIDs | change nothing; set the split metric (§4.3) |
| A node unreachable | skip it this round; report it in the metric |

Heal of one node `<r>` (`<shard>` from `system.clusters`). Each step was verified in the lab [V]:

1. If Keeper lists `<r>` under `/clickhouse/databases/<uuid>/replicas`, run on a healthy node:
   `SYSTEM DROP DATABASE REPLICA '<r>' FROM SHARD '<shard>' FROM DATABASE pmm`.
2. For every Replicated table in `pmm` whose Keeper path lists `<r>`, run on a healthy node:
   `SYSTEM DROP REPLICA '<r>' FROM TABLE pmm.<table>`.
3. On `<r>`: `CREATE DATABASE IF NOT EXISTS pmm UUID '<u>' ENGINE = Replicated('/clickhouse/databases/{uuid}', '{shard}', '{replica}')`.
4. Verify: both tables appear (the database worker retries every ~5 s); after `SYSTEM SYNC REPLICA pmm.metrics` the counts match.

Steps 1–2 remove Keeper metadata only, and are needed only after a volume loss (C9). After the install race or a `DROP DATABASE`, step 3 alone works. In the lab the healed node copied the full history, rows written while it lacked `pmm`, and schema changes made meanwhile; partitions dropped by retention meanwhile stayed dropped. An empty replication queue showed up before the copy finished (1.69M of 2.11M rows), so verification uses `SYSTEM SYNC REPLICA` and counts, not the queue.

Running from every pod at once is expected to be harmless, because `IF NOT EXISTS` with one UUID is idempotent [I, not run concurrently]. The two `SYSTEM DROP … REPLICA` statements are idempotent too [I].

### 4.3 Flag: split detection

- **Metric** from qan-api2 (C8). The author suggests `pmm_ha_qan_clickhouse_db_uuids` (distinct `pmm` UUIDs among reachable nodes) and `pmm_ha_qan_clickhouse_db_missing_nodes` (nodes without `pmm`, so a heal that keeps failing shows up).
- **Alert template** next to the HA ones (`managed/data/alerting-templates/ha_*.yml`, registered in `managed/services/alerting/provisioning_catalog.go`). It fires when the UUID count stays above 1. The description gives the exact repair command and a docs link.
- **Panel** on `dashboards/dashboards/PMM Health/PMM_HA_Health_Overview.json`: green with 1 UUID and 0 missing nodes.

### 4.4 Repair: command for a split (customer-run)

```sh
kubectl exec -n <namespace> pmm-ha-0 -c pmm-ha -- percona-qan-api2 clickhouse-repair            # dry run
kubectl exec -n <namespace> pmm-ha-0 -c pmm-ha -- percona-qan-api2 clickhouse-repair --apply    # repair
```

Any PMM pod works. It uses the connection settings and node discovery of §4.1.

**Dry run (default):** per node, prints the `pmm` UUID, `count()`, active parts and each table's Keeper path. Then prints the split kind, the copy it keeps, and what it would copy and drop. Changes nothing.

**Main copy:** the UUID most nodes share. A tie, or three UUIDs, needs `--keep <uuid>`. With no split it reports that and exits 0; it may run the heal (§4.2) for missing nodes.

**Split kind, per stray table, by comparing its Keeper path with the main copy's table of the same name:**

| Kind | Cause | Table Keeper paths | Data | Repair |
|---|---|---|---|---|
| S1 | qan-api2 recreated `pmm` (§2.4) | different | diverged | copy the stray rows, then re-home |
| S2 | restore on a node without `pmm` (§2.6) | same | shared | re-home only; copying would duplicate rows |

**`--apply`, for each node holding a stray copy** (each step verified in the lab [V]):

1. **S1 only, copy:**
   - `SYSTEM STOP MERGES pmm.metrics` on the stray node, so part names stay stable.
   - For each active part `p`, stream `SELECT <stray columns> FROM pmm.metrics WHERE _part = '<p>'` from the stray node into `INSERT INTO pmm.metrics (<stray columns>)` on a main node. Use small batches (C4) and `insert_deduplication_token = 'pmm-repair-<stray uuid>-<p>'`.
   - Record each copied part in a progress table on the stray node, in a separate database that the command creates and drops (e.g. `pmm_repair.copied_parts`), and skip recorded parts on a re-run. The token alone is not enough: the main table keeps only a window of recent tokens (`replicated_deduplication_window`), and live ingest (a batch every ≤ 500 ms, `qan-api2/models/data_ingestion.go:35`) can push them out within minutes [I].
   - Verify that the main copy has every copied row. The method is the builder's call; it must not count rows that live ingest adds during the repair.
2. **S2 only, check:** the stray node's tables are active members of the shared Keeper paths, and their active parts and queues match the main copy.
3. **Re-home:** `DROP DATABASE pmm SYNC` on the stray node, then at once `CREATE DATABASE pmm UUID '<main uuid>' ENGINE = Replicated(...)` there, then `SYSTEM SYNC REPLICA pmm.metrics`.
4. **Verify and print:** one UUID and the same table UUIDs on all nodes, and equal `count()` after sync.

Lab results [V]:
- **S1:** 15,000 stray rows in 3 parts. The copy was interrupted after 1 part and re-run twice in full; the main copy held exactly 15,000 of them. After re-homing, all nodes had 2,129,530 rows with identical per-day checksums.
- **S2:** re-homing alone gave one UUID, identical table UUIDs and identical rows and checksums.

**Requirements:**
- **Re-runnable at any point.** Killed between any two steps and run again, it ends in the same state with no rows lost or duplicated. It recognises "stray already dropped" and "already re-homed".
- **No rows lost while the leader writes to an S1 stray copy.** This case is **untested** (only a follower was attached in the lab). Either detect it and do a final pass over parts created since the first pass (merges are stopped, so new parts are new names), right before step 3, or refuse with a clear message. Which one is the builder's call.
- **S1 with rows overlapping the main copy:** refuse. Known S1 paths start from an empty stray copy, so the rows are disjoint.
- **A mixed or unknown state:** refuse and print why. That covers some tables S1 and others S2, more than one shard, or a node unreachable.
- Keep the logic in one function, so an API or UI button can call it later (out of scope here).

### 4.5 Backup and restore (`charts/pmm-ha/files/pmm-backup.sh`)

1. **Consistency check** used by `backup`, `restore` and `list`: read the `pmm` UUID on every ClickHouse pod. `pmm-backup.sh` already runs `clickhouse-client` in the pods; `kubectl exec` into each one avoids C1–C2.
2. **Backup:** run `clickhouse-backup create` on a pod that has `pmm`, not blindly on `items[0]` (`ch_resolve_pod`).
   - On a split: refuse and print the repair command.
   - With missing nodes: warn and continue (the backup is complete from a node with `pmm`). Record the `pmm` UUID and the node count in the manifest.
3. **Restore, before ClickHouse:**
   - **Split:** refuse and print the repair command.
   - **Missing nodes:** heal them first with the §4.2 statements. qan-api2 is scaled down during a restore, so this cannot wait for qan-api2.
   - **No node has `pmm`:** create it `ON CLUSTER` with an explicit UUID (§4.1 step 3).
   - Then run `clickhouse-backup restore` on a pod that has `pmm`.
4. **Restore, after ClickHouse:**
   - Verify one `pmm` UUID and the same table UUIDs on every pod, and row counts in sync after `SYSTEM SYNC REPLICA`.
   - Verify that `count()` of `pmm.metrics` matches the backup's count before PMM is scaled up. Record that count in the manifest at backup time, as the sum of `rows` over the parts the backup froze. A backup runs while QAN ingests, so a live `count()` would not match. PMM is scaled down during a restore, so nothing changes the restored count before this check.
   - On any mismatch: exit non-zero and mark the restore failed in the log and manifest. Never report "Restore complete".
5. **`list`:** show the consistency state, so a customer can check before restoring.

Whether `clickhouse-backup`'s `restore_schema_on_cluster` should be set is left to the builder. Steps 3–4 make the outcome correct either way.

### 4.6 Chart (percona-helm-charts)

- `wait-for-clickhouse`: check `system.clusters` on each node in `PMM_CLICKHOUSE_NODES`, not through the Service. Defense in depth; §4.1 closes the race on its own.
- `pmm-backup.sh` changes of §4.5, with its docs (`charts/pmm-ha/docs/pmm-backup.md`).
- **Operator:** after a volume loss it created nothing on the rebuilt node [V], so that case is a "missing" node for §4.2. Adding replicas was not tested. The operator's schemer copies database definitions without the UUID [V, code], so a scale-up could produce an S1 split, which §4.3 would flag. Scaling ClickHouse replicas is not a documented operation, so no chart change is planned for it.

---

## 5. Goals, non-goals, anti-goals

- **Goals:**
  - No new install ends with a node missing `pmm` or with two UUIDs.
  - Missing nodes heal on their own without data loss.
  - Splits are visible and repairable by the customer.
  - Backups capture QAN data, and restores either restore it or fail loudly.
- **Non-goals:**
  - a UI button for the repair;
  - changing qan-api2's sticky ClickHouse connection;
  - multi-shard layouts (refuse, don't guess);
  - ClickHouse replica scale-up.
- **Anti-goals:**
  - any automatic `DROP DATABASE` or row deletion;
  - qan-api2 ever generating a UUID while a node has `pmm`;
  - a repair that can lose or duplicate rows when interrupted;
  - a restore that reports success while ClickHouse is inconsistent or not restored.

---

## 6. Testing

**Unit:**
- the UUID decision tables (§4.1, §4.2);
- S1/S2 classification and main-copy choice (§4.4);
- re-run detection for every repair step;
- the `pmm-backup.sh` consistency check (bats or shell tests, following the chart's existing tests).

**Automated HA tests (ticket owner decision D14).** These go into the HA suites: pmm-qa `@pmm-ha` (Playwright, with its kubectl helpers) and/or the `pmm3-ha-tests` Jenkins job that runs a chart branch. Each has a lab reproduction from this ticket:

| # | Case | Pass |
|---|---|---|
| T1 | Fresh install, repeated (at least 5) | one UUID on every node, every time |
| T2 | `DROP DATABASE pmm SYNC` on a node no qan-api2 uses | healed within one routine interval; counts and checksums equal |
| T3 | Delete one ClickHouse node's PVC and pod | healed, including stale Keeper registrations; counts equal |
| T4 | Remove `pmm` from a node, then delete PMM follower pods until one starts against it | `pmm` recreated with the **existing** UUID |
| T5 | S1 split (made with the pre-fix logic or by SQL), rows in the stray copy | alert fires, panel red; repair dry run then `--apply`; stray rows present once on every node |
| T6 | T5, killing `--apply` between each pair of steps, then running it again | no rows lost or duplicated |
| T7 | S1 with the leader attached to the stray node during ingest | no rows lost, or a clear refusal |
| T8 | `pmm-backup.sh backup`, then `restore` in place | consistent; `count()` equals the backup's |
| T9 | Remove `pmm` from the restore pod, then `restore` | healed before restoring; consistent; `count()` equals the backup's |
| T10 | Split present, then `backup` and `restore` | both refuse and print the repair command |
| T11 | S2 split (T9's setup on pre-fix `pmm-backup.sh`) | repair re-homes without copying; rows equal, not doubled |
| T12 | Restore into a fresh install (another namespace) | consistent; `count()` equals the backup's |

**Docs:**
- the check command and `clickhouse-repair` in the PMM HA troubleshooting docs;
- `pmm-backup.md` updates;
- release note.

---

## 7. Decisions

| # | Decision | By |
|---|---|---|
| D1 | A split is flagged, never repaired automatically. | ticket owner |
| D2 | The customer runs the repair command; a UI button is out of scope, but the logic stays callable from an API. | ticket owner |
| D3 | Flag = built-in alert like the `pmm_ha_*` ones, plus an HA Health dashboard panel; the alert gives the command. | ticket owner |
| D4 | A node without `pmm` is healed automatically, only because the heal cannot drop or lose data (§4.2 rule). | ticket owner |
| D13 | `pmm-backup.sh` backup and restore are in scope. | ticket owner |
| D14 | The test cases in §6 become automated HA tests. | ticket owner |
| D5 | `pmm` is always created with an explicit UUID, reusing an existing one. | author |
| D6 | qan-api2 and the command use direct per-node connections from `PMM_CLICKHOUSE_NODES` (C1–C3). | author |
| D7 | The repair is a qan-api2 subcommand: dry run by default, `--apply` to act. | author |
| D8 | Main copy = the UUID most nodes share; ties need `--keep`. | author |
| D9 | S1 rows are copied per part: recorded in a progress table, with a dedup token as a second guard, merges stopped on the stray node, by column name, in bounded batches. | author |
| D10 | The heal removes stale Keeper registrations of a reachable node without `pmm` (volume loss). | author |
| D11 | The repair refuses an S1 stray copy that overlaps the main copy. | author |
| D12 | The first creation uses `ON CLUSTER` with an explicit UUID; later creations are per node with the existing UUID. | author |
| D15 | The split kind (S1/S2) is decided per table from Keeper paths; S2 is re-homed without copying. | author |
| D16 | `pmm-backup.sh` checks consistency before and after, works from a node that has `pmm`, heals before a restore, and fails loudly on mismatch. | author |

## 8. Left to the builder

- Metric names, routine interval, and alert thresholds and wording.
- How the S1 copy is verified (§4.4 step 1).
- Leader writing to an S1 stray copy: handle or refuse (§4.4).
- Copy batch size (C4).
- `restore_schema_on_cluster` (§4.5).
- Which HA suite each test case lives in, and how failure injection is done there.
