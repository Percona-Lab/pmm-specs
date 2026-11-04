# Aurora monitoring in PMM

*   **Author:** Tibi (tibor.korocz@percona.com)
*   **Status:** Draft
*   **Date:** 2026-11-04
*   **Epic:** [PMM-15868](https://perconadev.atlassian.net/browse/PMM-15868)
*   **Inputs:** [research.md](research.md) (live check and code reading), [concepts_brief.md](concepts_brief.md) (two review rounds)

--------------------------------------------------------------------------------

## Overview

PMM monitors Amazon Aurora instances added through RDS discovery, but treats them as plain RDS instances.
Its one Aurora dashboard is broken on Aurora MySQL 3, nothing groups instances by Aurora cluster, and cluster storage is never collected.

This design fixes that in two releases:

*   **Release 1, Aurora MySQL:**
    1.  rds_exporter publishes one small "info" series per instance, carrying the AWS cluster ID and engine it already receives from AWS.
    2.  rds_exporter collects Aurora cluster storage, which it requests today in a form AWS never answers.
    3.  A new Aurora overview dashboard, linked from the MySQL menu, lists instances grouped by AWS cluster.
    4.  The existing MySQL Amazon Aurora Details dashboard gets targeted fixes and rows for data PMM already collects.
    5.  Two generic panels that are empty on every RDS node (Disk Space, CPU Saturation) are fixed, which also helps plain RDS.
*   **Release 2, Aurora PostgreSQL:** the same overview covers Aurora PostgreSQL, with a details view and a writer/reader signal.

Nothing changes in RDS discovery, the PMM API, the add-instance form, inventory labels or PMM's database.

## The Problem

Checked on 2026-11-04 on a PMM 3.10.1 dev build, against two Aurora MySQL 3 instances (MySQL 8.0.42) and one Aurora PostgreSQL 15.15 instance, each a single-writer cluster ([research.md](research.md)).

*   **The Aurora dashboard is empty when opened normally.**
    MySQL Amazon Aurora Details builds both its service and node dropdowns from `mysql_global_status_auroradb_thread_deadlocks`, which Aurora MySQL 3 no longer reports.
    Opened without URL variables, every panel shows "No data".
    With `var-service_name` in the URL, 4 of its 6 panels are still partial or wrong (PMM-6655 is one of them).
    No PMM menu links to it; users reach it only through search.
*   **No view groups instances by Aurora cluster.**
    PMM stores no AWS cluster ID. The `cluster` label holds whatever the user typed, and rds_exporter's series never carry it.
*   **Cluster storage is never collected.**
    rds_exporter asks CloudWatch for `VolumeBytesUsed`, `VolumeReadIOPs` and `VolumeWriteIOPs` per instance, but AWS publishes them per cluster, so the 3 calls per instance per scrape always come back empty.
*   **Most collected Aurora data is never shown.**
    PMM collects 36 CloudWatch metrics per Aurora MySQL instance and about 130 Aurora status counters; all dashboards together use 4 `aws_rds_*` metrics.
*   **Two generic panels are empty on every RDS node.**
    Disk Space filters on a filesystem type that rds_exporter never reports, and CPU Saturation needs `node_cpu_seconds_total`, which RDS nodes do not have.
    The cause is in code that runs for every RDS instance, so plain RDS is very likely affected too (not tested).
*   **Aurora PostgreSQL has no dashboard.**
    Its replication collectors are skipped since PMM-14527, so reader lag and WAL panels on the generic PostgreSQL dashboards stay empty.

## Goals

Release 1:

1.  **Aurora details work when opened normally.**
    Opened from the menu, search or the overview with no URL variables, MySQL Amazon Aurora Details lists every Aurora MySQL service.
    On Aurora MySQL 3 under load, the panel sweep finds no empty and no partly empty panel, except rows labelled as needing a reader or Serverless.
2.  **One view of all Aurora MySQL clusters.**
    A new overview, linked from the MySQL menu, lists every monitored Aurora MySQL instance grouped by AWS region and cluster, including instances added before this change, with no label edits.
    An instance with no cluster information (no rds_exporter, an older pmm-client, or a failed AWS lookup) appears in an "AWS cluster unknown" group instead of disappearing.
3.  **Cluster storage is visible** for each Aurora cluster.
4.  **AWS requests do not grow.** rds_exporter's request count per Aurora instance, measured with `rds_exporter_requests_total`, is no higher than before.
5.  **Disk Space and CPU Saturation show data** for RDS nodes, Aurora and plain RDS alike.
6.  **No regression on plain RDS.** A plain RDS MySQL instance keeps every panel it has today and gets an info series with an empty cluster ID.

Release 2:

7.  Aurora PostgreSQL instances appear in the same overview, have a details view and a writer/reader signal, and WAL Writes is no longer empty on Aurora.

## Non-Goals

*   Changes to RDS discovery, its proto, the add-instance form, inventory labels or PMM's database. PMM UI changes are limited to the overview's menu entry.
*   New AWS permissions, and therefore `DescribeDBClusters` and everything that needs it: true cluster size, the writer flag from AWS, Serverless mode, Global Database.
*   Alert or advisor counts per cluster (no per-cluster data source exists), and new Aurora alert templates.
*   Writer/reader role or environment as labels; environment from AWS tags.
*   Plain RDS features that touch nothing this design changes, such as a panel for CloudWatch `FreeStorageSpace`. They go to a separate ticket.
*   The PostgreSQL Tuples panel's `instance=~"$node_name"` filter bug, which affects every PostgreSQL service. It goes to its own bug.
*   Aurora MySQL 2 (MySQL 5.7-compatible): past end of standard support, and no test instance runs it.
*   Converting panels this design doesn't otherwise touch from the old `graph` type.

## Open Questions

*   **Where cluster storage is fetched (D4).** Each Aurora instance asks for its cluster's `VolumeBytesUsed`, or rds_exporter groups instances and asks once per cluster per process. Decided in the Technical Plan.
*   **Which endpoint serves the info series (D1).** `/basic`, `/enhanced` or a new one; it must be exactly one.
*   **Whether the cluster key includes the AWS account (D3).** Needed only if one PMM monitors clusters with the same name in two accounts. Whether the account can be read from `DBInstanceArn` is unverified.
*   **rds_exporter self-reporting (D6).** At minimum a build-info series, so an old client can be told apart from a failure.
*   **Aurora PostgreSQL role signal and details view (D7, D8).** Release 2.
*   **Spikes before implementation**, on clusters that have a reader:
    *   Values of `innodb_read_only` and the PostgreSQL role signals on a reader, and during a failover.
    *   How often AWS publishes `VolumeBytesUsed`, and which query window shows it without gaps.
    *   Whether RDS Multi-AZ DB clusters (plain RDS) also set `DBClusterIdentifier`.
    *   What PMM-T1295 in pmm-qa asserts, so the new Details rows don't fail it.

## Critical User Journeys (CUJs)

### CUJ 1: See every Aurora cluster at a glance

*   **Given**: PMM Server and pmm-client from Release 1, and Aurora MySQL instances added through RDS discovery, some before the upgrade.
*   **When**: The user opens the Aurora overview from the MySQL menu.
*   **Then**: Instances are grouped by AWS region and cluster. Each group shows monitored instances, how many exporters are connected (N of M), throughput and cluster storage, and links to Details, Alerting and Advisors. No label was edited.

### CUJ 2: Drill into one instance

*   **Given**: The overview from CUJ 1.
*   **When**: The user clicks an instance.
*   **Then**: MySQL Amazon Aurora Details opens with that service selected, and every panel that applies to it has data.

### CUJ 3: Open the Aurora dashboard from search

*   **Given**: Release 1 installed.
*   **When**: The user finds MySQL Amazon Aurora Details through search, with no URL variables.
*   **Then**: Its service dropdown lists all Aurora MySQL services, and the first one's panels show data.

### CUJ 4: Server upgraded, pmm-client not yet

*   **Given**: PMM Server from Release 1, and Aurora instances whose rds_exporter runs on an older pmm-client.
*   **When**: The user opens the Aurora overview.
*   **Then**: Those instances appear in "AWS cluster unknown", with up/down and throughput still shown. Nothing errors, and they move to their cluster once the client is upgraded.

### CUJ 5: Disk and CPU on an RDS node

*   **Given**: An Aurora or plain RDS instance with Enhanced Monitoring on.
*   **When**: The user opens Node Summary or MySQL Instance Summary for it.
*   **Then**: Disk Space and CPU Saturation show data.

### CUJ 6 (Release 2): Aurora PostgreSQL in the same overview

*   **Given**: Aurora PostgreSQL instances added through RDS discovery, on Release 2.
*   **When**: The user opens the Aurora overview.
*   **Then**: Aurora PostgreSQL clusters appear next to Aurora MySQL ones, with a writer/reader signal and a link to their details view.

## Technical Plan (Architecture)

Release 1 changes two places: rds_exporter (shipped in pmm-client) and dashboard JSON plus one menu entry (shipped in PMM Server).
The database exporters, RDS discovery, the PMM API and inventory are untouched.

```text
                         AWS
   DescribeDBInstances (at start)      CloudWatch GetMetricStatistics
   ─ resource ID, interval (today)     ─ 47 per-instance metrics (today minus Volume*)
   ─ + cluster ID, engine, ARN (new)   ─ + VolumeBytesUsed by cluster, Aurora only (new)
                │                                   │
                ▼                                   ▼
   ┌──────────────────────── rds_exporter (pmm-client) ────────────────────────┐
   │ sessions: per instance, keeps cluster ID, engine, account (new)           │
   │ /enhanced (every 10 s): Enhanced Monitoring + aws_rds_instance_info (new)  │
   │ /basic    (every 60 s): CloudWatch metrics + cluster storage (new)         │
   │ build info series (new)                                                    │
   └──────────────────────────────────┬────────────────────────────────────────┘
                                      ▼
   mysqld_exporter / postgres_exporter ──► VictoriaMetrics ◄── (unchanged)
                                      │
                                      ▼
   Dashboards (PMM Server): Aurora overview (new), MySQL Amazon Aurora Details (fixed),
   Disk Space and CPU Saturation panels (fixed), MySQL menu entry (new)
```

### 1. rds_exporter: info series (D1: served on `/enhanced`)

*   **Read once at start.** The start-up `DescribeDBInstances` call (`rds_exporter:sessions/sessions.go`, `InstanceStates`) already returns every field needed.
    Keep three more values per instance next to `ResourceID`: `DBClusterIdentifier`, `Engine` and the account number taken from `DBInstanceArn`.
    None of them changes while the instance exists, and pmm-agent restarts rds_exporter whenever its configuration changes, so the start-up value stays current.
*   **Publish from memory on `/enhanced`.** A small collector registered on the enhanced registry emits one series per resolved instance, whatever its basic and enhanced switches say:

    ```text
    aws_rds_instance_info{instance="<AWS instance ID>", region="…", aws_cluster_id="<DBClusterIdentifier or empty>",
                          aws_engine="aurora-mysql|aurora-postgresql|mysql|postgres|…", aws_account_id="…",
                          <PMM node labels from the config>} 1
    ```

    The `aws_*` labels are set after the PMM labels, so a user label with the same name cannot overwrite them.
    `cluster` and `environment` are never touched; they stay the user's labels.
*   **Unresolved instances.** An instance the start-up lookup cannot resolve is already dropped until the next restart (existing behaviour). It gets no info series and lands in "AWS cluster unknown".
*   **Build info.** rds_exporter also exposes a standard `rds_exporter_build_info{version, …}` series, so a dashboard can tell "client too old" from "lookup failed".

### 2. rds_exporter: cluster storage (D4: per instance)

*   Remove `VolumeBytesUsed`, `VolumeReadIOPs` and `VolumeWriteIOPs` from the per-instance metric list (`rds_exporter:basic/metrics.go`), for every engine.
    AWS publishes them per cluster, nothing in PMM reads them, and they never return data per instance.
*   For instances whose engine starts with `aurora-`, the `/basic` scrape adds one call: `VolumeBytesUsed` with the `DBClusterIdentifier` dimension.
    The result is published as `aws_rds_volume_bytes_used_average` with the instance's usual labels plus `aws_cluster_id` and `aws_account_id`.
*   A cluster with N instances in PMM stores N identical copies; dashboards read it with `max by (region, aws_account_id, aws_cluster_id)` and never `sum`.
*   **Cost:** 48 CloudWatch calls per Aurora instance per scrape instead of 50; 47 per plain RDS instance instead of 50.
*   **Open (spike):** how often AWS publishes `VolumeBytesUsed`. rds_exporter queries a 10-minute window ending 10 minutes ago; if AWS publishes less often, the panel shows gaps, and the window for this one metric must widen.

### 3. Aurora overview dashboard (new)

*   **Where:** a new dashboard in `dashboards/dashboards/MySQL/`, registered in the pmm-app plugin, with an entry under MySQL in PMM's menu (`ui/apps/pmm/src/contexts/navigation/navigation.constants.ts`).
*   **Rows come from the database exporters, not the info series.**
    Start from `mysql_up`, left-join `aws_rds_instance_info` on `node_id`, and keep services where the joined `aws_engine` starts with `aurora-`.
    Services with no info series but with `mysql_global_status_auroradb_commits` go into an "AWS cluster unknown" group; this tells Aurora apart from plain RDS without the info series.
    A missing sample over the lookback window shows as down, not as a missing row.
*   **Per cluster (key: region, account, cluster ID):**

    | Column | Source | Freshness |
    |---|---|---|
    | Monitored instances | count of `mysql_up` rows | live |
    | Exporters connected (N of M) | `mysql_up` | live |
    | Throughput (queries/s) | `mysql_global_status_queries` | live |
    | Storage used | `aws_rds_volume_bytes_used_average`, `max` | about 10 minutes behind |

*   **Per instance (table under each cluster):** name, role (`innodb_read_only`: 0 writer, 1 reader, missing "unknown"), up/down, throughput, link to Details with `var-service_name`.
    A cluster whose writer count is not exactly 1 shows "changing", not an error, because role is sampled every 60 seconds.
*   **Links:** Alerting and Advisors pages (no per-cluster counts exist).
*   **Reuse:** Environments Overview (`dashboards/dashboards/PMM Health/Environments_Overview.json`) already has per-group counts, throughput and the `group_left` join; copy its structure with the AWS cluster key in place of `environment`.

### 4. MySQL Amazon Aurora Details (fixed)

Same file, uid (`mysql-amazonaurora`), variable names and panel ids, so existing links and bookmarks keep working.

*   **Variables:** `service_name` and `node_name` read `{__name__=~"mysql_global_status_auroradb_(commits|thread_deadlocks)"}`, which exists on Aurora MySQL 3 and 2. Remove the variables copied from other dashboards that no panel uses.
*   **Panel fixes:**
    *   Statement Latency: drop the query-cache term, fix the operator precedence in the SELECT expression, and show 0 instead of blank when a statement type is idle (closes PMM-6655).
    *   Problems: keep `aurora_reserved_mem_exceeded_incidents`; replace the two counters Aurora 3 dropped with CloudWatch `Deadlocks` and `BlockedTransactions`.
    *   Memory Used: keep lock manager memory; replace `aurora_dict_sys_mem_size` with temp-table RAM.
    *   Special Command Counters: one line per command instead of an average.
    *   Convert the six touched panels from `graph` to `timeseries`.
*   **New rows, each titled with when it has data:** buffer cache hit ratio and free local storage (CloudWatch); replication lag ("needs a reader"); write forwarding; parallel query; Serverless capacity ("Serverless only").
    The exact panels are listed in the Detailed Implementation.

### 5. Generic panels on RDS nodes (fixed; also plain RDS)

*   **Disk Space:** rds_exporter puts the filesystem name in `fstype`, which the panel's `fstype=~"(ext.|xfs|vfat|)"` filter rejects. Add a branch that, for RDS nodes (`node_type="remote_rds"`, verified on the live series), sums `node_filesystem_size_bytes` without the `fstype` filter.
*   **CPU Saturation:** for RDS nodes, compute saturation from `node_procs_running` and `rdsosmetrics_General_numVCPUs`, and max core usage from `node_cpu_average`, when `node_cpu_seconds_total` is missing.
*   **InnoDB data I/O panels** on MySQL Instances Overview: on Aurora, say the data doesn't apply instead of showing nothing.
*   The same panels appear on several summary dashboards; the Detailed Implementation lists every file.

### 6. Release 2: Aurora PostgreSQL (outline)

*   Overview rows from `pg_up`, same join and grouping, with throughput as commits per second.
*   Role from a plain postgres_exporter query on `pg_is_in_recovery()`, not a `query_aurora` entry, so it still runs if postgres_exporter's own Aurora detection fails (D7).
*   The info series decides what is Aurora; postgres_exporter's detection is not used for that.
*   WAL Writes on Aurora, and the details view's form (D8), are designed when Release 2 starts.

### Rollout

*   **Dashboards ship with PMM Server; rds_exporter ships with pmm-client.** No version gate is needed: there is no API, database or configuration change.
*   **New server, old client:** instances appear in "AWS cluster unknown", with up/down and throughput. Storage is missing until the client is upgraded.
*   **Old server, new client:** the extra series are collected but no dashboard uses them.
*   **Rollback:** reverting either side returns to today's behaviour; nothing is stored or migrated.

## Alternatives Considered

### Alternative A: Pre-fill the `cluster` label at RDS discovery

Discovery returns `DBClusterIdentifier`, and the add-instance form pre-fills the existing Cluster field.

*   **Pros**: The cluster shows in the form before adding; the user can change it; existing dashboards that filter by `cluster` start working.
*   **Cons**: Changes three places (API proto, pmm-managed, percona/grafana form) and needs a Feature Build across two repositories. Instances added before the change never get it. rds_exporter's series don't carry service labels, so CloudWatch data still could not be grouped by it. Changing a service's cluster label later deletes its scheduled backups.
*   **Reason for Rejection**: The info series gives the same grouping for all instances, old and new, with one rds_exporter change and no label edits.

### Alternative B: pmm-managed fills the cluster label when an instance is added

When an add request has no cluster, pmm-managed looks the instance up in AWS and fills it.

*   **Pros**: One repository; also covers instances added through the API.
*   **Cons**: One extra AWS call per add; the user can't see the value before adding; the same gaps as Alternative A for old instances and for CloudWatch series.
*   **Reason for Rejection**: Same as Alternative A.

### Alternative C: Use `DescribeDBClusters` for the writer flag, true cluster size and Serverless mode

*   **Pros**: Authoritative writer/reader role and the full member list, including members not added to PMM.
*   **Cons**: Needs `rds:DescribeDBClusters`, which PMM's documented IAM policy does not grant; users who followed the docs would get permission errors. The writer flag changes on failover, so it would need its own refresh.
*   **Reason for Rejection**: No new permissions. Role comes from `innodb_read_only`, which PMM already collects.

### Alternative D: Copy AWS tags into labels (for example, environment from a tag)

*   **Pros**: Customers' own tags, such as environment or owner, appear in PMM without typing.
*   **Cons**: Tag names differ per customer, so PMM can't know which one means environment. Labels would be a snapshot taken at add time, stale after the first retag. Many tag keys are not valid label names. Every tag becomes a label on every series.
*   **Reason for Rejection**: Not needed for grouping by cluster; environment stays a field users type.

### Alternative E: Build overview rows from the info series

*   **Pros**: Simplest query; the cluster key is on every row.
*   **Cons**: Instances without an info series disappear: those added without rds_exporter, those on an older pmm-client, and those whose start-up lookup failed. Counts and throughput come out low with no sign that anything is missing.
*   **Reason for Rejection**: Rows come from the database exporters, with an "AWS cluster unknown" group instead.

### Alternative F: Serve the info series on `/basic`, or on a new `/info` endpoint (D1)

*   **Pros**: `/basic` groups it with other AWS data; a new endpoint keeps it separate.
*   **Cons**: `/basic` responds only after all CloudWatch calls return; a slow or throttled CloudWatch past the 54-second timeout loses the whole response, so instances drop into "unknown" for that minute. A new endpoint needs a PMM server scrape-config change and a version check, because an older pmm-client would answer a newer server with 404.
*   **Reason for Rejection**: Owner decision D1: `/enhanced`, served from memory every 10 seconds, with no server change.

### Alternative G: Fetch cluster storage once per cluster per process (D4)

*   **Pros**: Fewer duplicate series; 47 calls per instance plus 1 per cluster.
*   **Cons**: Grouping code in rds_exporter; the series carries no node labels, so node-label filters don't apply; still duplicated when a cluster's instances run under different pmm-agents or credentials.
*   **Reason for Rejection**: Owner decision D4: one call per Aurora instance, read with `max` by cluster.

### Alternative H: Reuse rds_exporter's 5-minute refresh for the info series

The Enhanced Monitoring scraper already repeats `DescribeDBInstances` every 5 minutes.

*   **Pros**: The cluster ID and engine would refresh without a restart.
*   **Cons**: That refresh only covers instances with Enhanced Monitoring on, keeps its result private to that scraper, and lives in a 1,300-line file with its own locking. The values it would refresh never change for an instance.
*   **Reason for Rejection**: Read once at start; pmm-agent restarts rds_exporter on any configuration change.

### Alternative I: Alert and advisor counts per cluster on the overview

*   **Pros**: One screen answers "is anything wrong in this cluster?".
*   **Cons**: The advisor metric has only `service_type`, `advisor` and `check_name` labels; the Failed Advisors panel fetches every failed check without a filter; Grafana alert state is not stored as metrics; the built-in down templates drop `cluster`.
*   **Reason for Rejection**: No per-cluster data source exists. The overview links to the Alerting and Advisors pages.

### Alternative J: Rebuild the Aurora details dashboard from scratch

*   **Pros**: A clean layout designed for Aurora 3.
*   **Cons**: A new uid breaks bookmarks, links and the pmm-qa tests that open it; most of the dashboard needs about eight expression fixes, not a redesign.
*   **Reason for Rejection**: Targeted fixes plus named new rows, keeping the uid, file, variable names and panel ids.

### Alternative K: Remove the Aurora dashboard

The original handoff named this as the alternative to fixing it, given little recorded demand ([PMM-9191](https://perconadev.atlassian.net/browse/PMM-9191) has been On Hold since 2021).

*   **Pros**: Nothing to maintain.
*   **Cons**: Aurora users lose the only Aurora-specific view; the fixes are small and the data is already collected.
*   **Reason for Rejection**: The product owner chose to fix Aurora monitoring (this epic).

## Non-Functional Requirements

*   **AWS cost and quotas:** CloudWatch calls per scrape drop from 50 to 48 per Aurora instance and to 47 per plain RDS instance. `DescribeDBInstances` calls are unchanged. Measure before and after with `rds_exporter_requests_total`.
*   **Security:** no new AWS permission and no new stored data. The AWS account number appears as a metric label; it is not a secret, but it is visible to anyone who can read PMM metrics.
*   **Rollout and rollback:** see Rollout under the Technical Plan. No version gate, migration or flag.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

Release 1 only. Release 2 gets its own plan once D7 and D8 are decided.
Paths are relative to each repository's root. Line numbers are at the commits named in [research.md](research.md).

### Target Files to Create/Modify

#### percona/rds_exporter (ships in pmm-client)

#### 1. `sessions/sessions.go` (Modify)

*   **Type / Scope**: Go, AWS instance lookup.
*   **Proposed Changes**:
    *   Add `ClusterID`, `Engine` and `AccountID` to `InstanceState` and to `Instance`.
    *   In `InstanceStates`, fill them from `DBClusterIdentifier`, `Engine` and `DBInstanceArn` of each `DBInstance`. The account is the fifth `:`-separated field of the ARN (`arn:<partition>:rds:<region>:<account>:db:<id>`); an ARN that doesn't parse leaves it empty and logs a warning.
    *   In `New`, copy them into each resolved `Instance` next to `ResourceID`.
    *   **Why:** the start-up lookup already returns these fields; keeping them costs no AWS call.

#### 2. `sessions/sessions_test.go`, `sessions/resolver_test.go` (Modify)

*   **Type / Scope**: Go unit tests.
*   **Proposed Changes**: Cases for an Aurora instance (cluster ID, engine, account set), a plain RDS instance (empty cluster ID), and an ARN that doesn't parse (empty account, instance still resolved).

#### 3. `info/collector.go` (Create)

*   **Type / Scope**: Go, Prometheus collector.
*   **Proposed Changes**:
    *   A collector over `sessions.Sessions` that, on every `Collect`, emits `aws_rds_instance_info` = 1 for each resolved instance, from memory, with labels `region`, `instance`, the PMM labels from the instance config, then `aws_cluster_id`, `aws_engine`, `aws_account_id` set last so a config label can't overwrite them.
    *   It ignores `DisableBasicMetrics` and `DisableEnhancedMetrics`.
    *   **Why:** a separate package keeps it out of the 1,300-line enhanced scraper and makes the endpoint a one-line choice in `main.go`.

#### 4. `info/collector_test.go` (Create)

*   **Type / Scope**: Go unit test.
*   **Proposed Changes**: Exact output for an Aurora and a plain RDS instance; a config label named `aws_engine` does not replace the AWS value; an instance with both switches off still gets its series.

#### 5. `main.go` (Modify)

*   **Type / Scope**: Go, wiring.
*   **Proposed Changes**: Register the info collector and `version.NewCollector("rds_exporter")` (from `prometheus/common/version` v0.37, already a dependency; it provides `rds_exporter_build_info`) on the enhanced registry that serves `/enhanced` (D1).

#### 6. `basic/metrics.go` (Modify)

*   **Type / Scope**: Go, CloudWatch metric list.
*   **Proposed Changes**: Remove the `VolumeBytesUsed`, `VolumeReadIOPs` and `VolumeWriteIOPs` entries.
    The `go:generate` line in `basic/collector.go` points at a `basic/generate/` folder that doesn't exist, so edit the list by hand.

#### 7. `basic/scraper.go` (Modify)

*   **Type / Scope**: Go, CloudWatch scraper.
*   **Proposed Changes**:
    *   `NewScraper` keeps the `sessions.Instance` that `GetConfig` already returns, to read `Engine`, `ClusterID` and `AccountID`.
    *   For engines starting with `aurora-` and a non-empty cluster ID, `Scrape` adds one `GetMetricStatistics` call for `VolumeBytesUsed` with the `DBClusterIdentifier` dimension.
        It is published as `aws_rds_volume_bytes_used_average` with the instance's usual labels plus `aws_cluster_id` and `aws_account_id`.
    *   The query window for this metric stays the same as the others unless the spike shows AWS publishes it less often than every 10 minutes; then this one metric gets a longer window.

#### 8. `basic/collector_test.go`, `basic/testdata/all.txt` (Modify)

*   **Type / Scope**: Go tests and golden output.
*   **Proposed Changes**: Regenerate `all.txt` with `-golden-txt` (the test reads real CloudWatch through `config.tests.yml`, so it needs AWS credentials). Add a unit test, with no AWS call, for the rule "Aurora engine and cluster ID present → one extra cluster call".

#### 9. `CHANGELOG.md`, `README.md` (Modify)

*   **Type / Scope**: Docs.
*   **Proposed Changes**: Record the new series (`aws_rds_instance_info`, `rds_exporter_build_info`, cluster-level `aws_rds_volume_bytes_used_average`) and the three removed per-instance metrics.

#### percona/pmm (ships in PMM Server)

#### 10. `dashboards/dashboards/MySQL/Amazon_Aurora_Overview.json` (Create)

*   **Type / Scope**: Grafana dashboard, uid `aurora-overview`.
*   **Proposed Changes**:
    *   Variables: region only, read from `mysql_up`, with "All". No variable reads `aws_rds_instance_info`, so the dashboard opens the same way for instances on an older pmm-client.
    *   Cluster table: one row per (region, account, cluster), plus an "AWS cluster unknown" row. Columns: monitored instances, exporters connected (N of M), queries per second, storage used. Each column's description states its source and how fresh it is.
    *   Instance table: name, role from `mysql_global_variables_innodb_read_only` (writer, reader, unknown), up/down, queries per second, and a link to `mysql-amazonaurora` with `var-service_name`.
    *   Rows start from `mysql_up` and left-join `aws_rds_instance_info` on `node_id`; services without an info series but with `mysql_global_status_auroradb_commits` form the unknown group.
    *   Dashboard links to Alerting and Advisors.
    *   Structure copied from Environments Overview, with the AWS cluster key in place of `environment`.
    *   Run `dashboards/misc/cleanup-dash.py` on it.

#### 11. `dashboards/pmm-app/src/plugin.json` (Modify)

*   **Type / Scope**: Grafana plugin manifest.
*   **Proposed Changes**: Add the overview to `includes`, next to the existing "MySQL Amazon Aurora Details" entry, so Grafana provisions it.

#### 12. `ui/apps/pmm/src/contexts/navigation/navigation.constants.ts` (Modify)

*   **Type / Scope**: PMM UI, menu.
*   **Proposed Changes**: Add an "Amazon Aurora" child under `NAV_MYSQL` pointing to `/d/aurora-overview`. Update any navigation test or snapshot that lists the MySQL children.

#### 13. `dashboards/dashboards/MySQL/MySQL_Amazon_Aurora_Details.json` (Modify)

*   **Type / Scope**: Grafana dashboard, uid `mysql-amazonaurora` unchanged.
*   **Proposed Changes**:
    *   `service_name` and `node_name`: read `{__name__=~"mysql_global_status_auroradb_(commits|thread_deadlocks)"}`.
    *   Remove unused variables copied from other dashboards (`database`, `username`, `schema`, and the others no panel uses).
    *   Statement Latency: remove the `qcache_hits` term, fix the parentheses in the SELECT expression, and return 0 when a statement type has no executions.
    *   Problems: keep `aurora_reserved_mem_exceeded_incidents`; add CloudWatch `aws_rds_deadlocks_average` and `aws_rds_blocked_transactions_average`, matched by `node_name`.
    *   Memory Used: replace `aurora_dict_sys_mem_size` with `aurora_temptable_ram_allocation`.
    *   Special Command Counters: group by `command`.
    *   Convert the six panels to `timeseries`, keeping their ids and titles (pmm-qa matches them by title).
    *   New rows: "Cache and local storage" (buffer cache hit ratio, free local storage), "Replication (needs a reader)", "Write forwarding", "Parallel query", "Serverless capacity (Serverless only)".

#### 14. `dashboards/dashboards/MySQL/MySQL_Instances_Overview.json` (Modify)

*   **Type / Scope**: Grafana dashboard.
*   **Proposed Changes**: On the InnoDB data I/O panels (ids 437–443, 455–457), set the no-data text to say the data is not available on Amazon Aurora, so they no longer read as broken.

#### 15. Disk Space panel (Modify, 14 files)

*   **Files**: `dashboards/dashboards/MySQL/` `MySQL_Instance_Summary.json`, `MySQL_InnoDB_Details.json`, `MySQL_InnoDB_Compression_Details.json`, `MySQL_MyISAM_Aria_Details.json`, `MySQL_MyRocks_Details.json`, `MySQL_Performance_Schema_Details.json`, `MySQL_Query_Response_Time_Details.json`, `MySQL_Table_Details.json`, `MySQL_User_Details.json`, `MySQL_Wait_Event_Analyses_Details.json`; `dashboards/dashboards/PostgreSQL/PostgreSQL_Instance_Summary.json`; `dashboards/dashboards/OS/` `Node_Summary.json`, `Disk_Details.json`, `Nodes_Compare.json`.
*   **Type / Scope**: Grafana dashboards.
*   **Proposed Changes**: Add an `or` branch for `node_type="remote_rds"` that sums `node_filesystem_size_bytes` (and the free/available series where the panel uses them) without the `fstype` filter.
    The panel exists in three different versions across these files, so each version is edited by hand, not by search-and-replace.
*   **Not changed**: the MongoDB, HAProxy, ProxySQL, PMM Health and Experimental copies; RDS nodes don't appear there.

#### 16. CPU Saturation and Max Core Usage panel (Modify, 12 files)

*   **Files**: the ten MySQL files above, `PostgreSQL/PostgreSQL_Instance_Summary.json`, `OS/Node_Summary.json`.
*   **Type / Scope**: Grafana dashboards.
*   **Proposed Changes**: Add an `or` branch for RDS nodes: saturation from `node_procs_running` divided by `rdsosmetrics_General_numVCPUs`, max core usage from `node_cpu_average`. The panel exists in four versions; edit each by hand.

#### 17. `documentation/docs/reference/dashboards/dashboard-mysql-amazon-aurora-details.md` (Modify) and `dashboard-amazon-aurora-overview.md` (Create)

*   **Type / Scope**: User docs.
*   **Proposed Changes**: Describe the fixed and new panels, what "AWS cluster unknown" means, and that storage is about 10 minutes behind. Register the new page in the docs navigation, following [documentation/AGENTS.md](https://github.com/percona/pmm/blob/main/documentation/AGENTS.md).

#### 18. `documentation/docs/install-pmm/install-pmm-client/connect-database/aws.md` (Modify)

*   **Type / Scope**: User docs.
*   **Proposed Changes**: One paragraph: Aurora instances are grouped by AWS cluster automatically after upgrading pmm-client; no permission change is needed.

#### percona/pmm-qa (tests)

#### 19. `codeceptjs-e2e/tests/verifyAuroraMySQLRemoteInstance_test.js` (Modify)

*   **Type / Scope**: E2E test, PMM-T1295.
*   **Proposed Changes**: Add a scenario that opens MySQL Amazon Aurora Details without `service_name` in the URL and checks the dropdown has the service. Keep the existing "no empty graphs" check, which the reader-only and Serverless-only rows would fail on single-writer clusters, by collapsing those rows by default.

#### 20. `codeceptjs-e2e/tests/pages/dashboardPage.js`, `e2e_tests/testdata/dashboards.registry.ts` (Modify)

*   **Type / Scope**: Test page objects.
*   **Proposed Changes**: Add the overview (uid `aurora-overview`) and the new Details panel titles; keep the six existing titles.

### Verification Plan

*   **Compilation/Build**: rds_exporter `make` and `make check`. PMM UI `cd ui && make lint && make format-check`.
*   **Unit Tests**: rds_exporter `make test` (sessions, info, basic rule test). PMM UI `cd ui && make test`.
*   **Dashboard checks**: `python3 dashboards/misc/cleanup-dash.py --check-only <file>` for every changed dashboard, and `python3 -m unittest discover -s dashboards/misc -p 'test_*.py'`.
*   **Live check** (Feature Build with the rds_exporter and pmm branches, on a CHAOS VM), against Aurora MySQL 3 with a reader, Aurora MySQL 3 single writer, and one plain RDS MySQL instance:
    *   Panel sweep on the overview, Details, and every dashboard in items 15 and 16, for each service: no empty panel except rows marked as needing a reader or Serverless.
    *   Screenshots of both Aurora dashboards opened with no URL variables.
    *   `aws_rds_instance_info` present for every instance, with an empty cluster ID on plain RDS.
    *   `rds_exporter_requests_total` per minute before and after: no higher per instance.
    *   Role on the reader shows "reader"; after `aws rds failover-db-cluster`, the overview shows the new writer within two minutes.
    *   Old pmm-client with new server: instances appear under "AWS cluster unknown".
*   **E2E/Integration**: pmm-qa `@instances` runs PMM-T1295 against the Feature Build.

--------------------------------------------------------------------------------

*Drafted with EGM*
