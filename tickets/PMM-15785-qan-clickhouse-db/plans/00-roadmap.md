# QAN ClickHouse database consistency: roadmap and shared contract

> **For agentic workers:** this file is the index. Execute plans 01–03 one at a time, each with superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Every plan's tasks implicitly include the **Shared contract** and **Global constraints** below.

**Goal:** Every ClickHouse replica of a PMM HA install holds the same `pmm` database:
- new installs get it right;
- a node without `pmm` gets it back;
- existing splits are fixed once, after the upgrade;
- backups capture the most complete copy, and restores leave one `pmm` on every node.

Ticket [PMM-15785](https://perconadev.atlassian.net/browse/PMM-15785).

**Spec:** [`spec.md`](../spec.md), decisions in §7. Read it before any plan; the plans argue from it and do not repeat its evidence.

---

## Plans and order

| Plan | Scope | Repo | Depends on |
|---|---|---|---|
| [01](01-qan-api2.md) | Cluster test environment; node inspection; safe creation of `pmm`; the leader's routine that keeps every node on one `pmm`; metrics | percona/pmm | — |
| [02](02-pmm-backup.md) | `pmm-backup.sh`: per-pod check, backup from the pod with the most rows, restore that fixes `pmm` first, verification, docs | percona/percona-helm-charts | — (shares the SQL in the contract, not code) |
| [03](03-ha-tests.md) | Spec §6 cases T1–T9 as automated HA tests | percona/pmm-qa | 01–02 in a Feature Build |

- Plans 01 and 02 can run in parallel.
- Ship 01 and 02 together through one Feature Build (pmm + percona-helm-charts), and run plan 03 against it before merge.

**Branches:** `PMM-15785-qan-clickhouse-db` in percona/pmm (plan 01), percona/percona-helm-charts (plan 02, based on `main`) and percona/pmm-qa (plan 03).

**Docs:** in the same PRs (docs-in-code-PR process):
- plan 01: the PMM HA troubleshooting docs (UUID per node, the log lines) and the release-note draft;
- plan 02: `charts/pmm-ha/docs/pmm-backup.md`.

Add the docs reviewer to both PRs.

---

## Shared contract

These names are fixed across plans. A task that needs a name not listed here defines it in its own **Interfaces** block.

**Go package** `github.com/percona/pmm/qan-api2/chcluster` (new). License header: the AGPL header of `qan-api2/main.go:1-14`.

| Item | Value |
|---|---|
| Node list | env `PMM_CLICKHOUSE_NODES` (comma-separated FQDNs, set by the chart, `_helpers.tpl:266-274`); kingpin flag `--clickhouse-nodes`. Port: the port of `PMM_CLICKHOUSE_ADDR` (9000). |
| Cluster name | env `PMM_CLICKHOUSE_CLUSTER_NAME` (existing flag `--clickhouse-cluster-name`) |
| Database | env `PMM_CLICKHOUSE_DATABASE` (existing, default `pmm`) |
| Node state | `type NodeState struct { Host, Replica string; Reachable bool; DBUUID string; Rows uint64; TablePaths map[string]string; Shards, ClusterHosts int; Err error }`. `Replica` is the node's `replica` macro (spec C10). `DBUUID == ""` means no `pmm` database. `Rows` is `count()` of `<db>.metrics`. `TablePaths` maps table name to `system.replicas.zookeeper_path`. |
| Verdict | `type Verdict int` with `VerdictConsistent`, `VerdictMissing`, `VerdictSplit`, `VerdictNoDatabase`, `VerdictUnknown` |
| Engine clause | `ENGINE = Replicated('/clickhouse/databases/{uuid}', '{shard}', '{replica}')`, unchanged from `qan-api2/db.go:134` |
| Leader check | `GET http://127.0.0.1:7772/v1/ha/nodes`; the entry whose `node_name` equals env `PMM_HA_NODE_ID` has `role` `NODE_ROLE_LEADER` (spec C6). Anything else, including an error, means "not the leader". |

**Metrics** (qan-api2 `/debug/metrics`, default registry, namespace `qan_api2`, subsystem `clickhouse_cluster`; exported only when `PMM_CLICKHOUSE_NODES` is non-empty):

| Name | Type | Labels | Meaning |
|---|---|---|---|
| `qan_api2_clickhouse_cluster_db_uuids` | gauge | — | distinct `pmm` UUIDs among reachable nodes (1 healthy, >1 split, 0 none) |
| `qan_api2_clickhouse_cluster_db_missing_nodes` | gauge | — | reachable nodes without `pmm` |
| `qan_api2_clickhouse_cluster_db_unreachable_nodes` | gauge | — | nodes that could not be inspected |
| `qan_api2_clickhouse_cluster_repairs_total` | counter | `action` = `create`/`recreate`, `result` = `success`/`failure` | per node: `create` on a node without `pmm`, `recreate` on a node with another UUID |

**SQL** (spec §4.2, §4.3). `<r>` and `<shard>` are the `replica` and `shard` values from `system.macros` on the target node (chart: `chi-<release>-<cluster>-0-<n>` and `0`; `system.clusters.shard_num` is 1-based and is NOT the macro):

```sql
SELECT toString(uuid) FROM system.databases WHERE name = '<db>';
SELECT getMacro('replica');                                                        -- node identity; never hostName()
SELECT table, zookeeper_path FROM system.replicas WHERE database = '<db>';
SELECT name FROM system.zookeeper WHERE path = '/clickhouse/databases/<uuid>/replicas';
SYSTEM DROP DATABASE REPLICA '<r>' FROM SHARD '<shard>' FROM DATABASE <db>;        -- on a healthy node, only if listed
SYSTEM DROP REPLICA '<r>' FROM TABLE <db>.<table>;                               -- on a healthy node, per table, only if listed
DROP DATABASE <db> SYNC;                                                           -- on a node with another UUID
CREATE DATABASE IF NOT EXISTS <db> UUID '<u>' ENGINE = Replicated('/clickhouse/databases/{uuid}', '{shard}', '{replica}');
CREATE DATABASE IF NOT EXISTS <db> ON CLUSTER "<cluster>" UUID '<u>' ENGINE = Replicated('/clickhouse/databases/{uuid}', '{shard}', '{replica}');
```

Keeper registers a database replica as `<shard>|<replica>` (e.g. `0|chi-pmm-ha-pmmdb-0-2`) under `/clickhouse/databases/<uuid>/replicas`, and a table replica as `<replica>` under `<zookeeper_path>/replicas` (verified in the lab).

**pmm-backup.sh:** manifest fields `components.clickhouse.pmm_uuid` and `components.clickhouse.metrics_rows`.

---

## Global constraints

- qan-api2 never generates a UUID while any node has `pmm` (spec §4.1).
- Only the HA leader's qan-api2 drops, creates or recreates `pmm` after startup (D3). At startup a qan-api2 only creates `pmm` on nodes that Keeper does not list.
- Identify ClickHouse nodes by `getMacro('replica')`, never by `hostName()` (spec C10).
- One shard only: with more than one shard in `system.clusters` for the cluster, every routine reports `VerdictUnknown` and changes nothing.
- Direct connections use the PMM ClickHouse user and password already given to qan-api2; nothing new in secrets.
- Follow `AGENTS.md` of each repo: percona/pmm commits `PMM-15785 <summary>`, signed off (`-s`), no named returns, no inline `if err :=`, `sync.WaitGroup.Go`, testify, `t.Context()`.
- Non-chart installs (`PMM_CLICKHOUSE_NODES` empty) keep today's behaviour except that `pmm` is created with an explicit UUID (spec §4.1 step 3).
