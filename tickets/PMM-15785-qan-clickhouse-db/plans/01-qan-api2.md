# 01: qan-api2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** qan-api2 creates the `pmm` database only with a complete cluster view and an explicit, reused UUID. In the HA leader it keeps every ClickHouse node on one `pmm`: it recreates `pmm` on a node that lacks it, and fixes a split by keeping the copy with the most rows and recreating the others. It logs what it does; no metrics.

**Architecture:** A new package `qan-api2/chcluster` opens one direct connection per node from `PMM_CLICKHOUSE_NODES` (no `remote()`/`clusterAllReplicas()`, spec C1–C2), inspects each node, classifies the cluster and acts. `db.go` calls it instead of today's `createDB` when the node list is set. `main.go` runs `Converge` at start and every 10 minutes, only in the HA leader. Pure decisions (`Classify`, `KeepCopy`, the complete-view choice) are unit-tested on `NodeState` values; everything that talks to ClickHouse is tested against the Docker test cluster, so there is no interface or fake.

**Tech Stack:** Go 1.27, `clickhouse-go/v2` v2.49 via `database/sql` + `sqlx`, kingpin v2 (Percona fork), `net/http` (leader check), testify; docker compose for a 3-replica ClickHouse 25.8 + Keeper test cluster (the versions the chart runs).

**Spec:** [`../spec.md`](../spec.md) §2, §3, §4.1, §4.2, §5, D1–D4, D7, D9–D12; contract in [`00-roadmap.md`](00-roadmap.md).

## Global Constraints

The roadmap's global constraints and shared contract apply. In addition:
- **Code base:** percona/pmm `main` at `8540e366a` or later; branch `PMM-15785-qan-clickhouse-db`.
- **Completeness is a count:** a node's cluster view is complete when `SELECT count() FROM system.clusters WHERE cluster = '<cluster>'` equals `len(nodes)`. Host names there (`chi-…-0-N`) differ from the FQDNs in `PMM_CLICKHOUSE_NODES`, so do not compare names.
- **qan-api2 tests today:** single-node tests run with `make test-env-up && make test` (`qan-api2/Makefile:74-81`, ClickHouse 25.3.6.56 on port 19000). Cluster tests added here are behind build tag `chcluster`, so `make test` stays unchanged.
- **Drops:** only `Converge` drops `pmm`, only in the leader, only on a reachable node whose UUID differs from the kept one, and only right after a fresh leader check.

## Review Focus

1. **A node restarting during inspection.** Expected: it counts as unreachable, not as missing or split; nothing is done to it this pass. Test: `TestClassifyUnreachableIsNotMissing` (Task 2), `TestConvergeSkipsUnreachable` (Task 4).
2. **Two qan-api2 processes starting at once with no `pmm` anywhere.** Expected: one UUID on every node. Test: `TestEnsureDatabaseConcurrentCreatorsOneUUID` (Task 3).
3. **`PMM_CLICKHOUSE_NODES` with spaces, a trailing comma, or `host:port` entries.** Expected: parsed to clean `host:port` addresses; empty entries dropped. Test: `TestParseNodes` (Task 2).
4. **Leadership lost between the decision and a drop.** Expected: no drop. Test: `TestConvergeRechecksLeaderBeforeDrop` (Task 4).
5. **A split while a node does not answer.** Expected: nothing changes until every node answers, since that node may hold the larger copy. Test: `TestConvergeWaitsWhileANodeIsUnreachable` (Task 4).
6. **A split made by a pre-fix restore (shared table paths).** Expected: the stray node is recreated and no rows are lost. Test: `TestConvergeSharedPaths` (Task 4).
7. **A cluster with two shards.** Expected: `VerdictUnknown`, no action, a log line. Test: `TestClassifyMultiShardIsUnknown` (Task 2).
8. **qan-api2 starting while its own node lost its volume (stale Keeper registration).** Expected: it retries instead of exiting; the leader's loop fixes the node; qan-api2 then serves. Test: `TestNewDBWaitsForStaleNode` (Task 3).
9. **Split brain: two PMM pods each see themselves as leader.** Expected: no drop without a full view; creating `pmm` on an empty node still works. Test: `TestConvergeNeedsFullViewToDrop` (Task 4).
10. **A `pmm` without a `metrics` table** (crash after `CREATE`, interrupted restore, replica added by the operator). Expected: counts as 0 rows, the node stays reachable, and the split is fixed. Tests: `TestInspectMissingTableIsZeroRows` (Task 2), `TestConvergeSplitEmptyCopy` (Task 4).

---

### Task 1: Three-replica ClickHouse test cluster

**Files:**
- Create: `qan-api2/testdata/cluster/docker-compose.yml`, `qan-api2/testdata/cluster/config/{remote_servers.xml,zookeeper.xml,users.xml,keeper.xml}`, `qan-api2/testdata/cluster/config/macros-ch{1,2,3}.xml`
- Modify: `qan-api2/Makefile` (targets next to `test-env-up` at :74), `.github/workflows/qan-api2.yml` (new job after :36-48)
- Test: `qan-api2/chcluster/cluster_env_test.go` (build tag `chcluster`)

**Interfaces:**
- Produces: env `QANAPI_CLUSTER_NODES_TEST` (default `127.0.0.1:19101,127.0.0.1:19102,127.0.0.1:19103`), user `default`, password `clickhouse`, cluster name `pmmdb`, macros `shard=0`, `replica=ch1|ch2|ch3`. Make targets `cluster-env-up`, `cluster-env-down`, `cluster-node-reset NODE=chN` (recreates one node with an empty volume, Keeper kept), `test-cluster`.

- [ ] **Step 1: Write the failing test.** `TestClusterEnvironment`: for each node in `QANAPI_CLUSTER_NODES_TEST`, `SELECT count() FROM system.clusters WHERE cluster='pmmdb'` returns 3 and `SELECT substitution FROM system.macros WHERE macro='shard'` returns `"0"`.
- [ ] **Step 2: Run it:** `cd qan-api2 && go test -tags chcluster -run TestClusterEnvironment ./chcluster/` → FAIL (connection refused).
- [ ] **Step 3: Add the compose file and configs.**
  - Image `altinity/clickhouse-server:25.8.28.10001.altinitystable` for ch1–ch3 and `clickhouse/clickhouse-keeper:25.8.28.1` for `keeper`: the versions pmm-ha 1.8.0 runs, on which the spec's constraints were verified. The single-node `make test` stays on 25.3.
  - Host ports 19101–19103 → 9000, Keeper 19181. `remote_servers` defines cluster `pmmdb` with one shard and replicas `ch1`, `ch2`, `ch3`. Each node mounts its own `macros-chN.xml`.
  - Make targets: `cluster-env-up` runs `docker compose -f testdata/cluster/docker-compose.yml up -d --wait`; `cluster-node-reset` runs `rm -sfv` then `up -d --wait` for that service; `test-cluster` runs `go test -race -count=1 -tags chcluster ./chcluster/...`.
- [ ] **Step 4: Run it:** `make cluster-env-up && go test -tags chcluster -run TestClusterEnvironment ./chcluster/` → PASS.
- [ ] **Step 5: CI job** `cluster-tests` in `.github/workflows/qan-api2.yml`: `make install`, `make cluster-env-up`, `make test-cluster`, `make cluster-env-down` (always). Push and confirm the job is green.
- [ ] **Step 6: Commit** `PMM-15785 Add a three-replica ClickHouse test cluster`.

---

### Task 2: Node discovery, inspection and classification

**Files:**
- Create: `qan-api2/chcluster/cluster.go`
- Test: `qan-api2/chcluster/cluster_test.go`, `qan-api2/chcluster/cluster_cluster_test.go` (tag `chcluster`)

**Interfaces:**
- Produces:
  - `func ParseNodes(list, defaultAddr string) []string` — splits on `,`, trims, drops empties, appends the port of `defaultAddr` to entries without one.
  - `type Node struct { Addr string; DB *sqlx.DB }` — a concrete type, no interface. The queries are plain functions or methods on it.
  - `func OpenNodes(addrs []string, user, password string) []*Node` — one `sqlx` pool per address (`MaxOpenConns 2`, dial and read timeout 5 s); never fails, errors surface on use.
  - `type NodeState` and `type Verdict` from the shared contract; `func Inspect(ctx context.Context, nodes []*Node, db, cluster string) []NodeState` (fills `Replica` from `Macros` and `Rows` from `count()`, 0 when the table does not exist, code 60; only a failed connection sets `Reachable=false`); `func Classify(states []NodeState, wantNodes int) (Verdict, string)` returning the main UUID (majority; `""` on a tie).

- [ ] **Step 1: Write failing unit tests** (pure, on `NodeState` values):
  - `TestParseNodes`: `" a.svc , b.svc:9000,,c.svc "` with default `x:9000` → `["a.svc:9000","b.svc:9000","c.svc:9000"]`; `""` → `nil`.
  - `TestClassify` table: all `u1` → `VerdictConsistent, "u1"`; `u1,u1,""` → `VerdictMissing, "u1"`; `u1,u1,u2` → `VerdictSplit, "u1"`; `u1,u2,u3` → `VerdictSplit, ""`; `"","",""` → `VerdictNoDatabase, ""`.
  - `TestClassifyUnreachableIsNotMissing`: `u1,u1,<unreachable>` → `VerdictConsistent, "u1"`, and the unreachable state has `Reachable=false`.
  - `TestClassifyMultiShardIsUnknown`: any node reporting `shards=2` → `VerdictUnknown`.
- [ ] **Step 2: Run:** `go test -run 'TestParseNodes|TestClassify' ./chcluster/` → FAIL (undefined).
- [ ] **Step 3: Implement** `cluster.go`. `Inspect` queries each node concurrently (`sync.WaitGroup.Go`) with the contract SQL. It fills `Shards`/`ClusterHosts` from `ClusterSize`. A node reporting more than one shard makes `Classify` return `VerdictUnknown`.
- [ ] **Step 4: Run:** same command → PASS.
- [ ] **Step 5: Integration tests** (tag `chcluster`): `TestInspectCluster`: create `pmm_t2` on all nodes with `UUID '<random>' ON CLUSTER "pmmdb"` and a ReplicatedMergeTree `metrics` table, drop it on ch3 with `DROP DATABASE pmm_t2 SYNC` → `Classify` gives `VerdictMissing` and the UUID; `TablePaths` and `Rows` are right on ch1 and ch2; ch3 has `DBUUID ""`, `Rows 0`, `Reachable true`. `TestInspectMissingTable`: a `pmm_t2` without a `metrics` table → `Rows 0`, `Reachable true`. Run `make test-cluster` → PASS.
- [ ] **Step 6: Commit** `PMM-15785 Inspect pmm on every ClickHouse node`.

---

### Task 3: Create `pmm` safely

**Files:**
- Create: `qan-api2/chcluster/ensure.go`
- Modify: `qan-api2/db.go:42-148` (`NewDB`, `createDB`; the fatal exit at :81-83), `qan-api2/main.go:355-361` (flag), `qan-api2/main.go:396` (call)
- Test: `qan-api2/chcluster/ensure_test.go`, `qan-api2/chcluster/ensure_cluster_test.go` (tag `chcluster`), `qan-api2/db_cluster_test.go` (tag `chcluster`), `qan-api2/db_test.go` (`TestCreateDbIfNotExists` at :120)

**Interfaces:**
- Consumes: Task 2 `Node`, `Inspect`, `Classify`; Task 4 `CreateAndWait`.
- Produces:
  - `func EnsureDatabase(ctx context.Context, nodes []*Node, db, cluster string) (string, error)` — returns the UUID in use. It waits (1 s poll, until `ctx` ends) for a node whose `ClusterSize` hosts equal `len(nodes)`; that choice is a pure function of the states (`completeViewNode(states []NodeState, want int) int`). Then, by verdict:
    - `VerdictNoDatabase`: `ON CLUSTER` create with a new `uuid.NewString()`, run on that node;
    - `VerdictMissing`: `CreateAndWait` with the existing UUID, only on nodes that Keeper does not list under `/clickhouse/databases/<uuid>/replicas`; a node with a stale registration is left to the leader's `Converge`;
    - `VerdictConsistent`: nothing;
    - `VerdictSplit` / `VerdictUnknown`: `ErrSplit` / `ErrUnknown`, creating nothing.
  - Errors `ErrSplit`, `ErrUnknown` (exported vars).
  - New flag `--clickhouse-nodes` (`Envar("PMM_CLICKHOUSE_NODES")`, default `""`).
  - `NewDB(dsn string, maxIdleConns, maxOpenConns int, isCluster bool, clusterName string, nodes []string)`:
    - on `UNKNOWN_DATABASE` with `len(nodes) > 0` it calls `EnsureDatabase`;
    - when its own connection still gets `UNKNOWN_DATABASE` after `EnsureDatabase` (its node was skipped because Keeper lists it), or `EnsureDatabase` returns `ErrSplit`, it logs a warning and retries every 5 s instead of exiting (today's fatal exit at db.go:81-83). The leader's `Converge` runs independently (Task 5) and fixes that node or the split;
    - with no nodes it calls `createDB`, which now passes an explicit `UUID '<uuid.NewString()>'` in the cluster branch (spec §4.1 step 4). The cluster wait loop at db.go:45-68 stays for the no-nodes case.

- [ ] **Step 1: Write failing tests:**
  - `TestCompleteViewNode` (pure): states with 2 and 3 hosts and want 3 → the second; none complete → -1.
- [ ] **Step 2: Run** `go test -run TestCompleteViewNode ./chcluster/` → FAIL.
- [ ] **Step 3: Implement** `ensure.go` and the `db.go`/`main.go` changes (flag at main.go:355-361 next to `--clickhouse-cluster-name`; pass `ParseNodes(*clickhouseNodesF, *clickhouseAddrF)` at main.go:396).
- [ ] **Step 4: Run** the unit test → PASS; `make test-env-up && make test` → PASS (`TestCreateDbIfNotExists` unchanged in behaviour).
- [ ] **Step 5: Integration tests** (tag `chcluster`):
  - `TestEnsureDatabaseCreatesOnClusterWithUUID`: on an empty cluster the statement used is `UUID '<u>' ON CLUSTER "pmmdb"` in that order (spec C11); all nodes get `<u>`.
  - `TestEnsureDatabaseSplitCreatesNothing`: `u1` on ch1, `u2` on ch2, nothing on ch3 → `ErrSplit`; ch3 still has no `pmm`.
  - `TestEnsureDatabaseSkipsRegisteredNode`: after `make cluster-node-reset NODE=ch3` (Keeper still lists ch3) → no create on ch3, no error.
  - `TestEnsureDatabaseCreatesOneUUID`: on an empty cluster, all three nodes report the same UUID afterwards.
  - `TestEnsureDatabaseReusesExistingUUID`: `pmm` exists on ch1–ch2 only (created `ON CLUSTER`, then `DROP DATABASE … SYNC` on ch3) → ch3 gets the same UUID.
  - `TestEnsureDatabaseConcurrentCreatorsOneUUID`: two goroutines call `EnsureDatabase` on an empty cluster → both return the same UUID, and all nodes match.
  - `TestNewDBRetriesOnSplit`: own node ch3 without `pmm`, `u1` on ch1 and `u2` on ch2 → `NewDB` keeps retrying; a goroutine runs `Converge` as the leader after 10 s → `NewDB` returns a working pool.
  - `TestNewDBWaitsForStaleNode`: `pmm` on all nodes, then `make cluster-node-reset NODE=ch3` (Keeper keeps the registration); `NewDB` with its DSN on ch3 → it does not return or exit while ch3 lacks `pmm`; a goroutine runs `Converge` as the leader after 10 s → `NewDB` returns a working pool.
  Run `make test-cluster` → PASS.
- [ ] **Step 6: Commit** `PMM-15785 Create pmm with one UUID on every node`.

---

### Task 4: `Converge`: one `pmm` on every node

**Files:**
- Create: `qan-api2/chcluster/converge.go`
- Test: `qan-api2/chcluster/converge_test.go`, `qan-api2/chcluster/converge_cluster_test.go` (tag `chcluster`)

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - `type RepairResult struct { Host, Action, OldUUID, NewUUID string; DroppedRows uint64; Err error }`. `Action` is `create` or `recreate`.
  - `func CleanRegistrations(ctx context.Context, target, healthy *Node, db, uuid string) error` — reads the target's macros `(shard, replica)`, then on `healthy`:
    1. `SYSTEM DROP DATABASE REPLICA '<replica>' FROM SHARD '<shard>' FROM DATABASE <db>`, only if `/clickhouse/databases/<uuid>/replicas` lists `<shard>|<replica>` (via `system.zookeeper`);
    2. `SYSTEM DROP REPLICA '<replica>' FROM TABLE <db>.<t>` for each table whose `<zookeeper_path>/replicas` lists `<replica>`.
  - `func CreateAndWait(ctx context.Context, target, healthy *Node, db, uuid string) error` — on the target, the per-node `CREATE DATABASE IF NOT EXISTS … UUID '<uuid>'`, then poll `system.tables` until it has every table `healthy` has (timeout 2 min). It does not wait for rows (spec C4).
  - `func KeepCopy(states []NodeState) (string, error)` — the UUID with the most `Rows` among reachable nodes, then the lowest UUID; `ErrWait` when any node is unreachable.
  - `func Converge(ctx context.Context, nodes []*Node, db, cluster string, ha func(context.Context) (leader, fullView bool)) []RepairResult` — `ha` is Task 5's `HAStatus`:
    1. `Inspect` and `Classify`. `VerdictConsistent`, `VerdictNoDatabase` or `VerdictUnknown`: return nothing.
    2. The kept UUID: with `VerdictMissing`, the main UUID; with `VerdictSplit`, `KeepCopy`. On `ErrWait`: log and return nothing.
    3. For each reachable node with another UUID, in order:
       - `ha(ctx)` must return leader and full view, otherwise stop: no drop in a split brain or after leadership moved;
       - read the UUID again on a node of the kept copy; if it is not the kept UUID any more, stop;
       - record `count()` of `<db>.metrics`, `DROP DATABASE <db> SYNC`, then as for a node without `pmm` (`recreate`).
    4. For each reachable node without `pmm`: `CleanRegistrations` with a node that has the kept UUID, then `CreateAndWait` (`create`).
    5. Log each result at warning level: node, action, old and new UUID, dropped rows, error.

- [ ] **Step 1: Write the failing unit test** (pure): `TestKeepCopy` table: `u1,u1,u2` with rows 10,000, 10,000, 500 → `u1`; `u1,u2` with `u2` more rows → `u2`; equal rows (including all 0) → the lower UUID; any node unreachable → `ErrWait`.
- [ ] **Step 2: Run** `go test -run TestKeepCopy ./chcluster/` → FAIL.
- [ ] **Step 3: Implement** `converge.go`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Integration tests** (tag `chcluster`; `pmm_t4` on all nodes with a ReplicatedMergeTree table `metrics` holding 10,000 rows):
  - `TestConvergeAfterDrop`: `DROP DATABASE pmm_t4 SYNC` on ch3 → ch3 has the same UUID and, after `SYSTEM SYNC REPLICA`, 10,000 rows.
  - `TestConvergeAfterVolumeLoss`: `make cluster-node-reset NODE=ch3` (Keeper keeps the registration); a plain create fails with code 253 (`REPLICA_ALREADY_EXISTS`), and `Converge` succeeds with 10,000 rows on ch3.
  - `TestConvergeSplitKeepsMostRows`: ch3 holds a stray `pmm_t4` (another UUID, own Keeper path, 500 marked rows) → ch3 recreated with ch1's UUID; 10,000 rows on every node; no marked rows.
  - `TestConvergeSplitLargerStray`: the stray holds 20,000 marked rows → ch1 and ch2 recreated with the stray's UUID; 20,000 marked rows on every node.
  - `TestConvergeSharedPaths`: ch3's stray `pmm_t4.metrics` uses ch1's Keeper path → ch3 recreated; 10,000 rows on every node before and after.
  - `TestConvergeSplitEmptyCopy`: on ch3, `CREATE DATABASE pmm_t4 ENGINE = Replicated('/clickhouse/databases/{uuid}', '{shard}', '{replica}')` without a UUID and without tables (the operator's statement for a new replica, spec C12) → ch3 recreated with ch1's UUID; 10,000 rows on every node.
  - The guards, against the same cluster with `ha` as a test function: `TestConvergeRechecksLeaderBeforeDrop` (`ha` turns false after the decision → no drop), `TestConvergeNeedsFullViewToDrop` (leader without full view → no drop, the empty node is still created), `TestConvergeRechecksKeptUUIDBeforeDrop` (the kept node's UUID changes before the drop → no drop), `TestConvergeWaitsWhileANodeIsUnreachable` (a split with ch3 stopped → nothing changes).
  Run `make test-cluster` → PASS.
- [ ] **Step 6: Commit** `PMM-15785 Keep every ClickHouse node on one pmm database`.

---

### Task 5: Leader check and periodic routine

**Files:**
- Create: `qan-api2/chcluster/leader.go`
- Modify: `qan-api2/main.go` (flag block :348-366, routine near :441-445)
- Test: `qan-api2/chcluster/leader_test.go`, `qan-api2/consistency_test.go`

**Interfaces:**
- Consumes: Tasks 2 and 4.
- Produces:
  - `func HAStatus(ctx context.Context, c *http.Client, baseURL, nodeID string) (leader, fullView bool)` — the roadmap's leader check and full view; both `false` on any error or an empty `nodeID`. Base URL `http://127.0.0.1:7772`, node ID from env `PMM_HA_NODE_ID`, an HTTP client with a 5 s timeout.
  - `func runConsistencyLoop(ctx context.Context, interval time.Duration, check func(context.Context))` in `main.go`. It runs at start and then every `interval`, waiting with a `time.Timer` and `select` on `ctx.Done()`, the same as `runRetentionLoop` at main.go:298-343.
  - Flag `--clickhouse-consistency-interval` (hidden, default `10m`).

- [ ] **Step 1: Write failing tests:**
  - `TestConsistencyLoopRunsAtStartAndStops`: 10 ms interval, cancel after the second call → exactly 2 calls, then the loop returns.
  - `TestHAStatus` (`httptest` server returning the `/v1/ha/nodes` JSON shape): own node `NODE_ROLE_LEADER` with 3 of `expected_nodes: 3` alive → `true, true`; leader with 2 nodes listed → `true, false`; leader with one node not `alive` → `true, false`; `NODE_ROLE_FOLLOWER` → `false, …`; HTTP 500 or own node absent → `false, false`.
- [ ] **Step 2: Run** `go test -run 'TestConsistencyLoop|TestHAStatus' ./ ./chcluster/` → FAIL.
- [ ] **Step 3: Implement.** In `main.go`, only when `len(nodes) > 0`:
  - `wg.Go(func() { runConsistencyLoop(ctx, *consistencyIntervalF, check) })`, started **before** `NewDB` (main.go:396) with its own `OpenNodes`, so it runs even while `NewDB` retries (spec §4.1 step 3). `check` runs `Converge` (with `HAStatus` bound to the HTTP client and node ID) only when `HAStatus` reports the leader. Followers do nothing.
- [ ] **Step 4: Run** the tests → PASS; `make check` (golangci-lint) → no new findings.
- [ ] **Step 5: Docs and release note.** In the PMM HA troubleshooting docs under `documentation/docs/` (find the page with `grep -rl "High Availability" documentation/docs | grep -i troubleshoot`): how to read the `pmm` UUID on each ClickHouse pod, what the qan-api2 log lines about `create` and `recreate` mean, and that a split on an existing install is fixed in the first pass after the upgrade, dropping rows that exist only in the other copy. Add the release-note draft for the ticket.
- [ ] **Step 6: Commit** `PMM-15785 Run the pmm consistency routine in the HA leader`.

---

### Task 6: Feature Build check on a PMM HA install

**Files:** none (verification only; record results in the PR description).

- [ ] **Step 1:** Open a Feature Build with this branch (pmm-dev:pmm-feature-build). Install pmm-ha with the FB image on a 3-node cluster.
- [ ] **Step 2:** Confirm that qan-api2 sees the node list: `kubectl exec -n pmm pmm-ha-0 -c pmm-ha -- sh -c 'tr "\0" "\n" < /proc/$(pgrep -f percona-qan-api2)/environ | grep -E "PMM_CLICKHOUSE_NODES|PMM_HA_NODE_ID"'` prints three FQDNs and the pod name. If not, add the variables to the qan-api2 program environment in `managed/services/supervisord/supervisord.go:299-309` and repeat.
- [ ] **Step 3:** On one ClickHouse pod run `DROP DATABASE pmm SYNC`. Within 10 min the pod has `pmm` with the others' UUID, and the leader's qan-api2 log shows one `create`.
- [ ] **Step 4:** On a ClickHouse pod that QAN does not write to, create a stray copy in one `clickhouse-client --multiquery` call, so nothing recreates `pmm` in between:
  1. `DROP DATABASE pmm SYNC`, then `CREATE DATABASE pmm UUID '<new>' ENGINE = Replicated(…)`;
  2. create each table from `SHOW CREATE TABLE` on another pod, with the `UUID` clause and engine arguments removed;
  3. copy the `schema_migrations` rows from another pod;
  4. insert a few thousand marked rows.

  Within 10 min the pod is recreated with the main UUID, the leader's log shows one `recreate` with the dropped row count, and `/v1/qan/metrics:getReport` kept answering.
