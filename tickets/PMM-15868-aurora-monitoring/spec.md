# Aurora monitoring in PMM

*   **Author:** Tibi (tibor.korocz@percona.com)
*   **Status:** Release 1 implemented, in code review. Live checks of plain RDS and of an Aurora PostgreSQL reader are pending (see [Verification](#verification-and-acceptance-criteria)).
*   **Date:** 2026-11-04, updated to the as-built design on 2026-11-06
*   **Epic:** [PMM-15868](https://perconadev.atlassian.net/browse/PMM-15868)
*   **Inputs:** [research.md](research.md) (live check and code reading before this epic), [concepts_brief.md](concepts_brief.md) (two review rounds, history only)

--------------------------------------------------------------------------------

## Overview

PMM monitors Amazon Aurora and RDS instances added through RDS discovery, but treated Aurora as plain RDS.
Its one Aurora dashboard was broken on Aurora MySQL 3, nothing grouped instances by Aurora cluster, and cluster storage was never collected.

Release 1, as built:

1.  **rds_exporter** publishes one info series per instance with the AWS cluster ID, engine, account and read-replica source, taken from the `DescribeDBInstances` calls it already makes. It also collects Aurora cluster storage, publishes CloudWatch `FreeableMemory` under its own name and leaves `fstype` empty on filesystem series.
2.  **A native PMM UI page, Amazon RDS > Overview**, lists every Aurora MySQL, Aurora PostgreSQL, RDS for MySQL, MariaDB and PostgreSQL instance. It groups them by Aurora cluster, Multi-AZ DB cluster or replication group, and shows status, role, firing alerts, throughput and storage.
3.  **pmm-managed** adds a viewer-allowed endpoint that lists Node types, which the menu needs, and copies the Service's `environment`, `cluster` and `replication_set` labels onto rds_exporter series so that LBAC roles see them.
4.  **MySQL Amazon Aurora Details** works on Aurora MySQL 3 without URL variables and gains CloudWatch and cluster storage panels.
5.  **Generic panels:** Disk Space works on RDS nodes, and so does CPU Saturation when Enhanced Monitoring is on.

Release 2 (an Aurora PostgreSQL details view and WAL Writes on Aurora) is still to be designed.
There is no database migration, no new AWS permission, and no change to RDS discovery or the add-instance form.

## Decision Log

Changes from the design as first reviewed, and why.

| # | Change | Why |
|---|---|---|
| 1 | The overview is a native PMM UI page (`/pmm-ui/amazon-rds`, top-level menu **Amazon RDS > Overview**), not a Grafana dashboard. The planned "Amazon Aurora Overview" dashboard under MySQL and an interim Grafana panel-plugin prototype were dropped. | Grafana's nested tables can't do per-row links or field config in the Grafana version PMM ships, and when PMM upgrades Grafana is not known. The panel plugin also needed an unsigned-plugin allowance. A top-level landing page fits the PMM UI, like Real-Time Analytics. |
| 2 | Scope widened from Aurora MySQL to plain RDS (MySQL, MariaDB, PostgreSQL) and Aurora PostgreSQL. | The info series and the grouping need nothing Aurora-specific, so the other RDS engines came at little cost. |
| 3 | Firing alerts per group and instance are in scope. Advisor counts are still out. | Grafana's alert rules API carries `service_name` and `node_name`, which a native page can read; the earlier rejection assumed a dashboard reading metrics only. Advisor results still have no per-service source. |
| 4 | The info series' AWS values are refreshed every 5 minutes from the enhanced scraper's existing `DescribeDBInstances` call, not only read at start (reverses Alternative H). | Read-replica sources change when a replica is promoted, and cluster storage must follow the instance's current cluster. The refresh adds no AWS call. |
| 5 | The info series also carries `aws_source_instance_id` and `aws_source_region`. | Replication groups (primary and read replicas, also cross-region) are built from them. |
| 6 | rds_exporter series carry the Service's `environment`, `cluster` and `replication_set` when all Services on the Node agree on them. This corrects the earlier "no inventory label change". | With LBAC roles filtering on these labels, every rds_exporter series was hidden: the page showed every instance under "AWS info unavailable" and the RDS node dashboards were blank. |
| 7 | New endpoint `POST /v1/inventory/nodes:getTypes` (`ListActiveNodeTypes`), allowed for viewers; an additive change to the PMM API. | The menu shows only when an RDS Node exists, and listing Nodes needs the Admin role. |
| 8 | CloudWatch `FreeableMemory` becomes `aws_rds_freeable_memory_average`. | It was stored as `node_memory_Cached_bytes`, which Enhanced Monitoring also uses for the OS cache. |
| 9 | Aurora Details also gets an "Instance resources (CloudWatch)" row, a "Cluster volume used" panel and a link to the Amazon RDS page. | CloudWatch data is there for every instance, Enhanced Monitoring or not. |
| 10 | CPU Saturation's RDS branch needs Enhanced Monitoring; it is documented, with no CloudWatch fallback. | CloudWatch reports CPU utilization, not saturation. |
| 11 | QA: two Playwright tests; the planned CodeceptJS change to PMM-T1295 was dropped. | pmm-qa's rule: new UI tests go to Playwright. |

## The Problem

Checked on 2026-11-04 on a PMM 3.10.1 dev build, against two Aurora MySQL 3 instances (MySQL 8.0.42) and one Aurora PostgreSQL 15.15 instance, each a single-writer cluster ([research.md](research.md)).

*   **The Aurora dashboard is empty when opened normally.**
    MySQL Amazon Aurora Details builds its service and node dropdowns from `mysql_global_status_auroradb_thread_deadlocks`, which Aurora MySQL 3 no longer reports.
    With `var-service_name` in the URL, 4 of its 6 panels are still partial or wrong (PMM-6655 is one of them). No PMM menu links to it.
*   **No view groups instances by Aurora cluster** or shows the RDS estate at all.
    PMM stores no AWS cluster ID; the `cluster` label holds whatever the user typed, and rds_exporter's series never carry it.
*   **Cluster storage is never collected.**
    rds_exporter asks CloudWatch for `VolumeBytesUsed`, `VolumeReadIOPs` and `VolumeWriteIOPs` per instance, but AWS publishes them per cluster, so 3 calls per instance per scrape always come back empty.
*   **Most collected Aurora data is never shown.**
    PMM collects 36 CloudWatch metrics per Aurora MySQL instance and about 130 Aurora status counters; all dashboards together use 4 `aws_rds_*` metrics.
*   **Two generic panels are empty on every RDS node.**
    Disk Space filters on a filesystem type that rds_exporter never reports, and CPU Saturation needs `node_cpu_seconds_total`, which RDS nodes do not have.
*   **Aurora PostgreSQL has no dashboard.**
    Its replication collectors are skipped since PMM-14527, so reader lag and WAL panels on the generic PostgreSQL dashboards stay empty.

## Goals

Release 1:

1.  **Aurora details work when opened normally.** Opened from the menu, search or the Amazon RDS page with no URL variables, MySQL Amazon Aurora Details lists every Aurora MySQL service, and its panels have data except rows labelled as needing a reader, a feature in use, or Serverless.
2.  **One view of every RDS and Aurora database.** The Amazon RDS page lists every MySQL and PostgreSQL service on a `remote_rds` Node, grouped by Aurora cluster, Multi-AZ DB cluster or replication group, including instances added before the upgrade, with no label edits.
    An instance without AWS details (an older pmm-client, or a failed AWS lookup) appears under "AWS info unavailable" instead of disappearing.
3.  **Health at a glance.** For each group and instance: exporters connected, writers or role, firing alerts, throughput and storage.
4.  **Same visibility as the dashboards.** Users with the Viewer role see the menu and the page, and LBAC roles see the instances they may see.
5.  **Cluster storage is visible** for each Aurora cluster.
6.  **AWS requests do not grow:** fewer CloudWatch calls per instance, and no extra `DescribeDBInstances` call.
7.  **Disk Space and CPU Saturation show data** for RDS nodes: Disk Space once rds_exporter is upgraded, CPU Saturation when Enhanced Monitoring is on.
8.  **No regression on plain RDS.**

Release 2:

9.  Aurora PostgreSQL gets a details view, and WAL Writes is no longer empty on Aurora. Listing and role on the Amazon RDS page shipped in Release 1.

## Non-Goals

*   Changes to RDS discovery, its proto, the add-instance form or PMM's database.
*   New AWS permissions, and therefore `DescribeDBClusters` and everything that needs it: true cluster size, the writer flag from AWS, Serverless mode, Global Database, and linking a replica of a Multi-AZ DB cluster or an Aurora cross-region replica cluster to its source.
*   Advisor counts per group, and new Aurora alert templates.
*   Writer/reader role or AWS tags as labels; environment from AWS tags.
*   Listing instances added with `pmm-admin add mysql|postgresql`: they don't run on a `remote_rds` Node.
*   A CloudWatch fallback for CPU Saturation.
*   The PostgreSQL Tuples panel's `instance=~"$node_name"` filter bug (its own bug), Aurora MySQL 2, and converting untouched panels from the old `graph` type.

## Open Questions and Known Limitations

The design questions are settled: D1 (info series on `/enhanced`), D3 (the key includes the AWS account, read from `DBInstanceArn`), D4 (cluster storage per instance, read with `max`), and D7 (Aurora PostgreSQL role from the existing `pg_replication_is_replica` and `pg_settings_in_hot_standby`). D8, the Aurora PostgreSQL details view, waits for Release 2.

Known limitations and follow-ups:

*   **Show all in Alert groups** filters on `node_name` only, so an alert that names an instance only through `service_name` is counted on the page but not listed there.
*   Under a search, a group's alert badge also counts alerts of the instances the search hides.
*   Aurora MySQL added with `pmm-admin` gets no Deadlocks line in Problems: the status counter Aurora 3 dropped was replaced by CloudWatch `Deadlocks`, which needs rds_exporter.
*   The new no-data text on the InnoDB data I/O panels mentions Aurora also for non-Aurora instances that have no data.
*   Aurora PostgreSQL 13 and older shows role "unknown": `pg_settings_in_hot_standby` needs PostgreSQL 14, and the replication collectors are skipped on Aurora.
*   A replica of a Multi-AZ DB cluster shows as a standalone instance, and an Aurora cross-region replica cluster as its own cluster; linking them needs `DescribeDBClusters`.
*   Sessions whose instances all disable enhanced metrics make no refresh call, so their info values stay as read at start-up until rds_exporter restarts.
*   rds_exporter's session keying, unchanged by this epic, mixes up the same instance name in two accounts in one region, and several IAM roles behind one access key.
*   Pending live checks: see [Verification](#verification-and-acceptance-criteria).

## Critical User Journeys (CUJs)

### CUJ 1: See every RDS and Aurora database at a glance

*   **Given**: PMM Server and pmm-client from Release 1, and instances added through RDS discovery, some before the upgrade.
*   **When**: A user with the Viewer role or higher opens **Amazon RDS > Overview**.
*   **Then**: One row per group, ordered by region and account: Aurora cluster, Multi-AZ DB cluster, replication group (named after the primary) or standalone instance. Each shows connected and monitored instances, writers, firing alerts, throughput and storage. No label was edited.

### CUJ 2: Drill into one instance

*   **Given**: The page from CUJ 1.
*   **When**: The user expands a group and clicks an instance.
*   **Then**: The engine's main dashboard opens in a new tab with that service selected: Aurora Details for Aurora MySQL, MySQL Instance Summary for MySQL and MariaDB, PostgreSQL Instance Summary for PostgreSQL and Aurora PostgreSQL. **MySQL** and **OS** links open MySQL Instance Summary and Node Summary.

### CUJ 3: Open the Aurora dashboard from search

*   **Given**: Release 1 installed.
*   **When**: The user finds MySQL Amazon Aurora Details through search, with no URL variables.
*   **Then**: Its service dropdown lists the Aurora MySQL services only, and the first one's panels show data.

### CUJ 4: Something is firing

*   **Given**: A firing, unsilenced alert whose `service_name` or `node_name` names a listed instance.
*   **When**: The user clicks the alert badge of its group or instance.
*   **Then**: A list of the alerts, each linking to its rule's Instances tab, plus **Show all in Alert groups**.

### CUJ 5: Server upgraded, pmm-client not yet

*   **Given**: PMM Server from Release 1, and instances whose rds_exporter runs on an older pmm-client on another host.
*   **When**: The user opens the page.
*   **Then**: Those instances appear under "AWS info unavailable", one group per region and engine, with status, role and throughput. They move to their groups once that pmm-client is upgraded.
*   **Note**: instances added through RDS discovery run rds_exporter on PMM Server's own pmm-agent by default (`managed/services/management/rds.go`, `models.PMMServerAgentID`), so upgrading PMM Server is enough for them.

### CUJ 6: Disk and CPU on an RDS node

*   **Given**: An Aurora or plain RDS instance with Enhanced Monitoring on, monitored by a Release 1 pmm-client.
*   **When**: The user opens Node Summary or MySQL Instance Summary for it.
*   **Then**: Disk Space and CPU Saturation show data.

## Technical Plan (Architecture)

```text
                                AWS (no new permissions)
   DescribeDBInstances, at start and every 5 min    CloudWatch GetMetricStatistics
   from the enhanced scraper (existing calls):      ─ 47 per-instance metrics (Volume* removed)
   + cluster ID, engine, account, replica source    ─ + VolumeBytesUsed by cluster, Aurora only
                   │                                               │
                   ▼                                               ▼
   ┌───────────────────────────── rds_exporter (pmm-client) ─────────────────────────────┐
   │ /enhanced: Enhanced Monitoring + aws_rds_instance_info                               │
   │ /basic:    CloudWatch + aws_rds_volume_bytes_used_average; FreeableMemory renamed    │
   │ labels from pmm-managed: Node, shared Service labels (new), Agent                    │
   └──────────────────────────────────────────┬───────────────────────────────────────────┘
                                              ▼
            mysqld_exporter / postgres_exporter ──► VictoriaMetrics
                                              │
        Grafana /api/ds/query (Metrics data source, LBAC)      Grafana alert rules + Alertmanager
                                              │                              │
                                              ▼                              ▼
   PMM UI: Amazon RDS > Overview (/pmm-ui/amazon-rds); menu gated by POST /v1/inventory/nodes:getTypes
   Dashboards: Aurora Details, CPU Saturation, Disk Space (via empty fstype), InnoDB I/O no-data text
```

### 1. rds_exporter: info series (D1: `/enhanced`)

*   **AWS values.** `InstanceStates` (`rds_exporter:sessions/sessions.go`) keeps, next to `ResourceID`: `DBClusterIdentifier`, `Engine`, the account from `DBInstanceArn`, and the read-replica source from `ReadReplicaSourceDBInstanceIdentifier`. A same-region source is a plain identifier; a cross-region one is an ARN, which gives the source region. An ARN that doesn't parse leaves the account empty and logs a warning.
*   **Refresh.** Values are read at start and refreshed every 5 minutes, when the enhanced scraper repeats `DescribeDBInstances` for its session (`enhanced/scraper.go`, `updateInstanceStates`). The scraper passes the result to `Sessions.UpdateInstanceStates`, which updates every instance of the session, including those with enhanced metrics disabled. A lock guards the instances; `AllSessions` and `GetConfig` return copies.
*   **Series.** A collector (`info/collector.go`) on the enhanced registry emits, from memory, one series per resolved instance, whatever its basic and enhanced switches say:

    ```text
    aws_rds_instance_info{instance="<DB instance ID>", region="…", <labels from the config>,
                          aws_cluster_id="…", aws_engine="aurora-mysql|aurora-postgresql|mysql|mariadb|postgres|…",
                          aws_account_id="…", aws_source_instance_id="…", aws_source_region="…"} 1
    ```

    The `aws_*` labels are set last, so a config label with the same name can't overwrite them. `aws_cluster_id` is empty outside a cluster, and the `aws_source_*` labels are empty for instances that are not read replicas.
*   **Unresolved instances** are dropped until the next restart (existing behaviour); they get no info series and land under "AWS info unavailable".

### 2. rds_exporter: cluster storage and other series (D4: per instance)

*   `VolumeBytesUsed`, `VolumeReadIOPs` and `VolumeWriteIOPs` are removed from the per-instance metric list (`basic/metrics.go`): AWS publishes them per cluster.
*   For engines starting with `aurora` (the legacy `aurora` engine included) and a non-empty cluster ID, each `/basic` scrape adds one `VolumeBytesUsed` call with the `DBClusterIdentifier` dimension of the instance's current cluster. It is published as `aws_rds_volume_bytes_used_average` with the instance's labels plus `aws_cluster_id` and `aws_account_id`.
*   AWS publishes it irregularly, often 45 to 70 minutes late (spike, 2026-11-04), so this one metric reads the newest datapoint of the 3 hours ending 10 minutes before the scrape: it can be up to about 3 hours 10 minutes old.
*   A cluster with N monitored instances stores N identical copies; readers use `max`, never `sum`.
*   **Cost:** 48 CloudWatch calls per Aurora instance per scrape instead of 50, 47 per plain RDS instance.
*   `FreeableMemory` is published as `aws_rds_freeable_memory_average` instead of `node_memory_Cached_bytes`.
*   `node_filesystem_*` series have an empty `fstype` (`enhanced/metrics.go`, `makeNodeFilesystemMetrics`); see section 6.

### 3. pmm-managed: labels and the Node types endpoint

*   **Service labels on rds_exporter series.** `managed/services/agents/rds.go` (`mergeLabels`, `sharedServiceLabels`) merges Node labels, then `environment`, `cluster` and `replication_set` from the Services on the Node, then Agent labels, which is the order Service series use. A label is copied only when every Service on the Node has the same non-empty value; a Node without Services gets none. `service_name` stays off, so Node-level series keep joining Service series through `node_name`.
    `state.go` loads the Services of all RDS Nodes with one query per pmm-agent state (`models.FindServicesByNodeIDs`). Adding, changing or removing a Service through the inventory API requests a state update of the pmm-agents that run an rds_exporter for its Node (`managed/services/inventory/services.go`), so the labels follow without a restart.
*   **`POST /v1/inventory/nodes:getTypes`** (`ListActiveNodeTypes` in `api/inventory/v1/nodes.proto`, additive) returns the distinct Node types in the inventory, like `services:getTypes` does for Services. `managed/services/grafana/auth_server.go` allows it for the Viewer role.

### 4. Amazon RDS page (PMM UI)

*   **Route and menu.** `ui/apps/pmm/src/pages/amazon-rds/`, at `/pmm-ui/amazon-rds`. The top-level **Amazon RDS** menu, with one child **Overview**, sits with the dashboard menus. It appears when `nodes:getTypes` includes `NODE_TYPE_REMOTE_RDS_NODE` (refetched every 5 minutes), for every role.
*   **Data.** Instant PromQL through Grafana's `/api/ds/query` on the Metrics data source (`ui/apps/pmm/src/api/metrics.ts`, `api/rds.ts`), so LBAC applies and viewers may query. One request every 60 seconds runs 8 queries:

    | Query | Source | Required |
    |---|---|---|
    | up | `mysql_up` or `pg_up` with `node_type="remote_rds"`; a service that stopped reporting stays as 0 for one hour | yes |
    | info | `aws_rds_instance_info`, also kept for one hour after it stops | yes |
    | role | Aurora MySQL `mysql_global_variables_innodb_read_only`; MySQL and MariaDB `mysql_global_variables_read_only`; PostgreSQL `pg_replication_is_replica` or `pg_settings_in_hot_standby` | no |
    | throughput | MySQL family `rate(mysql_global_status_queries)`; PostgreSQL `rate(pg_stat_database_xact_commit)` + `rate(pg_stat_database_xact_rollback)` | no |
    | storage | Aurora `aws_rds_volume_bytes_used_average`; others `aws_rds_free_storage_space_average`, or Enhanced Monitoring `node_filesystem_free_bytes` | no |

    A failed required query shows an error; a failed optional one leaves its values blank. Grafana answers 400 for the whole request when one query fails, with every result in the body.
    Rows start from the database exporters' `up` series and take AWS labels from the info series by `node_id`, so a service without an info series is never lost (Alternative E). Only services on `remote_rds` Nodes are listed.
*   **Grouping** (`AmazonRds.utils.ts`, `groupInstances`):
    *   **Aurora cluster** or **Multi-AZ DB cluster:** same region, account and `aws_cluster_id`; the engine decides which.
    *   **Replication group:** a primary and its read replicas, found through `aws_source_instance_id` and `aws_source_region`, cross-region and cascaded replicas included, and named after the primary even when PMM doesn't monitor it.
    *   **Instance:** standalone.
    *   **AWS info unavailable:** no info series, one group per region and engine. The engine falls back to the PMM service type, and its writer count raises no warning.
*   **Group columns:** Region / Account; DB identifier; Type / Engine; Alerts; Instances / Writers ("connected / monitored", then the writer count: "no writer" and more than one writer are warnings, "unknown" when no instance reports its role); Throughput (qps for the MySQL family, tps for PostgreSQL); Storage (Aurora: cluster volume used, `max` across instances; others: free storage, the lowest instance marked "(min)"). Secondary values sit on a second line, so the table fits beside the open side menu down to a 1280 px screen.
*   **Instance rows** (expand per group or all, writers first): service link to the engine's main dashboard, **MySQL** and **OS** dashboard links, the AWS instance ID and region where they differ from the service and group, role, status (Up/Down), alerts, throughput and storage (none for Aurora instances). All links open in a new tab.
*   **Alerts.** Firing alerts from Grafana's alert rules API, excluding those that Grafana's Alertmanager reports as silenced, the same way the Alerts page does. An alert belongs to an instance when its `service_name` or `node_name` names it. Counts stay unknown until both requests succeed, so a silenced alert never counts as firing. The badge is coloured by the worst severity band and opens a list that links each alert to its rule's Instances tab, plus **Show all in Alert groups** (Grafana Alert groups filtered by `node_name`, active alerts only). The header has **Alerting** (Alerts > Status) and, for Editors and Admins when Advisors are enabled, **Advisors**.
*   **Search and filters.** Search matches DB identifiers, types, regions, engines, accounts, service names and instance IDs; a group matched only through some instances opens with just those. Region (the instances' regions too, so a cross-region replica is found), AWS account, Engine, Type and DB identifier filters take several values. All are kept in URL parameters `rds-q`, `rds-region`, `rds-account`, `rds-engine`, `rds-type`, `rds-id`.

### 5. MySQL Amazon Aurora Details

Same file, uid (`mysql-amazonaurora`), variable names and panel ids, so links and bookmarks keep working.

*   **Variables:** `service_name` and `node_name` read `{__name__=~"mysql_global_status_auroradb_(commits|thread_deadlocks)"}`, which exists on Aurora MySQL 3 and 2. Variables no panel used are removed.
*   **Panel fixes:** Statement Latency drops the query-cache term, fixes the SELECT expression and shows 0 for an idle statement type (PMM-6655). Problems keeps `aurora_reserved_mem_exceeded_incidents` and replaces the two counters Aurora 3 dropped with CloudWatch Deadlocks and BlockedTransactions. Memory Used replaces `aurora_dict_sys_mem_size` with temp-table RAM. Special Command Counters shows one line per command. The six panels are now `timeseries`.
*   **New rows:** "Cache and local storage" (buffer cache hit ratio, free local storage, cluster volume used); "Instance resources (CloudWatch)", expanded (CPU utilization, freeable memory, connections, IOPS, throughput, network throughput, disk queue depth, swap); collapsed "Replication (needs a reader)", "Write forwarding", "Parallel query" and "Serverless capacity (Serverless only)".
*   A dashboard link opens the Amazon RDS page.

### 6. Generic panels on RDS nodes

*   **Disk Space:** fixed in rds_exporter by the empty `fstype`, which every Disk Space filter (`fstype=~"(ext.|xfs|vfat|)"`) already accepts and every exclusion filter passes. No dashboard change (Alternative M).
*   **CPU Saturation and Max Core Usage** (12 dashboards): for `node_type="remote_rds"`, saturation is `node_procs_running` divided by `rdsosmetrics_General_numVCPUs`, plus a "CPU Utilization (all cores, RDS)" line from `node_cpu_average`. Both come from Enhanced Monitoring; without it the panel stays empty, as documented in the release notes.
*   **InnoDB data I/O panels** on MySQL Instances Overview say in their no-data text that Aurora doesn't report InnoDB data file I/O.

### 7. Release 2: Aurora PostgreSQL (outline)

Listing, grouping, role and throughput shipped with the Amazon RDS page. Left: a details view (D8), WAL Writes on Aurora, and a role signal for Aurora PostgreSQL 13 and older.

### Rollout

*   **The page, endpoint, label change and dashboards ship with PMM Server; rds_exporter ships with pmm-client.** RDS-discovery instances run rds_exporter on PMM Server's pmm-agent by default, so a PMM Server upgrade covers them. No version gate: the endpoint and its only caller ship together.
*   **New server, old client:** instances appear under "AWS info unavailable" with status, role and throughput. Cluster storage, Disk Space, and Aurora Details' Freeable memory panel stay empty until the client is upgraded.
*   **Old server, new client:** the new series are unused. Custom dashboards or alert rules that read `node_memory_Cached_bytes` of RDS nodes as freeable memory must switch to `aws_rds_freeable_memory_average`, and filters on RDS `fstype` must change (both in the release notes).
*   **Label change:** after the upgrade, or after changing a Service's `environment`, `cluster` or `replication_set`, an RDS node's graphs can show its series twice for a few minutes.
*   **Rollback:** reverting either side returns to the previous behaviour; nothing is stored or migrated, and the labels follow the next state update.

## Alternatives Considered

### Alternative A: Fill the `cluster` label with the AWS cluster ID, at discovery or when an instance is added

Discovery pre-fills the existing Cluster field from `DBClusterIdentifier`, or pmm-managed looks it up when an add request has none.

*   **Pros**: The cluster shows in the form; dashboards that filter by `cluster` start working.
*   **Cons**: Changes the API proto, pmm-managed and the percona/grafana form, or costs one AWS call per add. Instances added before the change never get it. The field is the user's, so it can't be trusted to hold the AWS cluster, and changing it later deletes the Service's scheduled backups.
*   **Reason for Rejection**: The info series groups all instances, old and new, with no label edits.

### Alternative C: Use `DescribeDBClusters` for the writer flag, cluster size, Serverless mode and cluster replicas

*   **Pros**: Authoritative role and member list; would link Multi-AZ DB cluster replicas and Aurora cross-region replica clusters to their source.
*   **Cons**: Needs `rds:DescribeDBClusters`, which PMM's documented IAM policy does not grant; users who followed the docs would get permission errors.
*   **Reason for Rejection**: No new permissions. Role comes from metrics PMM already collects.

### Alternative E: Build the page's rows from the info series

*   **Pros**: Simplest query; the group key is on every row.
*   **Cons**: Instances without an info series disappear, and counts and throughput come out low with no sign that anything is missing.
*   **Reason for Rejection**: Rows come from the database exporters, with an "AWS info unavailable" group.

### Alternative H: Read the info values only at start-up (the reviewed design)

*   **Pros**: No state shared with the enhanced scraper.
*   **Cons**: A promoted replica would keep its source, and cluster storage would follow a stale cluster ID, until pmm-agent restarts rds_exporter.
*   **Reason for Rejection**: The enhanced scraper's 5-minute refresh already makes the call; sharing its result costs a lock, not an AWS request.

### Alternative N: The overview as a Grafana dashboard (the reviewed design and a prototype)

Two variants were built: two tables on the Environments Overview pattern, then a custom pmm-app panel plugin showing a cluster tree.

*   **Pros**: Ships as dashboard JSON; no UI code.
*   **Cons**: Nested tables can't do per-row links or field config in PMM's Grafana version, and when PMM upgrades Grafana is not known. The plugin needed an unsigned-plugin allowance in `grafana.ini`.
*   **Reason for Rejection**: A native page, like Real-Time Analytics, fits a top-level landing page (Decision 1).

### Alternative O: Copy every Service label onto rds_exporter series, or none

*   **Pros**: Either is simpler than copying three labels on agreement.
*   **Cons**: Copying all (including `service_name`) breaks the `node_name` join between Node and Service series, and on a Node with several Services it picks one Service's values. Copying none leaves LBAC roles blind to RDS metrics (Decision 6).
*   **Reason for Rejection**: Copy only the standard labels LBAC filters on, and only when the Node's Services agree.

### Smaller alternatives

| Alternative | Reason for rejection |
|---|---|
| D: Copy AWS tags into labels | Tag names differ per customer, labels would be a snapshot taken at add time, many tag keys are not valid label names, and every tag would land on every series. |
| F: Serve the info series on `/basic` or a new `/info` endpoint (D1) | `/basic` loses its whole response when CloudWatch runs past the 54-second timeout; a new endpoint needs a scrape-config change and a version check. |
| G: Fetch cluster storage once per cluster per process (D4) | Grouping code in rds_exporter, and a series without Node labels escapes LBAC and Node filters. |
| I: Advisor counts per group | The advisor metric has only `service_type`, `advisor` and `check_name` labels. The page links to Advisors instead. |
| J: Rebuild Aurora Details from scratch | A new uid breaks bookmarks, links and tests; about eight expression fixes were enough. |
| K: Remove the Aurora dashboard | The product owner chose to fix Aurora monitoring (this epic). |
| L: An rds_exporter build-info series (D6) | PMM scrapes rds_exporter as a bare target (`managed/services/victoriametrics/scrape_configs.go`), so the series can't be tied to an instance. |
| M: Fix Disk Space in the dashboards | 14 files with the panel in 3 versions; an empty `fstype` in rds_exporter fixes every copy at once. |

## Non-Functional Requirements

*   **AWS cost and quotas:** CloudWatch calls per scrape drop from 50 to 48 per Aurora instance and to 47 per plain RDS instance. `DescribeDBInstances` calls are unchanged.
*   **Security:** no new AWS permission and no new stored data. The page reads metrics through Grafana with the user's LBAC filters and alerts through Grafana's APIs with the user's permissions; the new endpoint shows viewers only which Node types exist. The AWS account number appears as a metric label; it is not a secret, but anyone who can read the metric sees it.
*   **Load:** the page sends one Grafana query request (8 instant queries) and two alerting requests per minute while open. pmm-managed adds one Services query per pmm-agent state that has RDS Nodes.
*   **Rollout and rollback:** see Rollout. No version gate, migration or flag.

--------------------------------------------------------------------------------

## Files Changed

Paths are relative to each repository's root.

#### percona/rds_exporter (ships in pmm-client)

*   `sessions/sessions.go`, `sessions/sessions_test.go`, `sessions/resolver_test.go`: AWS values per instance, ARN parsing, `UpdateInstanceStates`, lock and copies.
*   `info/collector.go`, `info/collector_test.go`, `main.go`: the info series on `/enhanced`.
*   `enhanced/scraper.go`, `enhanced/collector.go`, `enhanced/scraper_test.go`: the 5-minute refresh feeds the sessions.
*   `basic/metrics.go`, `basic/scraper.go`, `basic/scraper_test.go`, `basic/collector_test.go`, `basic/testdata/all.txt`: `Volume*` removed, cluster storage, `FreeableMemory` renamed.
*   `enhanced/metrics.go`, `enhanced/testdata/*.txt`: empty `fstype`.
*   `README.md`, `CHANGELOG.md`.

#### percona/pmm (ships in PMM Server)

*   **API:** `api/inventory/v1/nodes.proto` and its generated files, `api/swagger/`; `managed/models/node_helpers.go`, `managed/services/inventory/nodes.go`, `managed/services/inventory/grpc/nodes_server.go`, `managed/services/grafana/auth_server.go`, with unit tests; `api-tests/inventory/nodes_test.go`, `api-tests/server/auth_test.go`.
*   **Labels:** `managed/services/agents/rds.go`, `managed/services/agents/state.go`, `managed/models/service_helpers.go`, `managed/services/inventory/services.go`, with unit tests.
*   **UI:** `ui/apps/pmm/src/pages/amazon-rds/` (page, tables, toolbar, alerts badge, utils, tests); `api/rds.ts`, `api/metrics.ts`, `api/nodes.ts`; `hooks/api/useRds.ts`, `hooks/api/useNodes.ts`; `contexts/navigation/`; `router.tsx`; `lib/constants.ts`; `types/`.
*   **Dashboards:** `dashboards/dashboards/MySQL/MySQL_Amazon_Aurora_Details.json`, `MySQL_Instances_Overview.json`; CPU Saturation in the ten MySQL details and summary dashboards, `PostgreSQL/PostgreSQL_Instance_Summary.json` and `OS/Node_Summary.json`.
*   **Docs:** `documentation/docs/use/amazon-rds-overview.md` (new), `reference/dashboards/dashboard-mysql-amazon-aurora-details.md`, `install-pmm/install-pmm-client/connect-database/aws.md`, `use/dashboards-panels/index.md`, `admin/roles/index.md`, `mkdocs-base.yml`, `release-notes/next.md` (the page, Aurora Details, CPU Saturation and Enhanced Monitoring, the `FreeableMemory` rename, empty `fstype`, Service labels on RDS metrics, PMM-6655); `documentation/api/inventory/list-node-types.md` (new).

#### percona/pmm-qa (tests)

*   `e2e_tests/tests/inventory/remoteInstances.test.ts`: PMM-T2504 (the Amazon RDS page lists the Aurora instance under its cluster, with type, engine, instances, writer, role, status and a new-tab link to Aurora Details) and PMM-T2505 (Aurora Details lists Aurora MySQL services without URL variables, and its panels have data), both `@instances`, version-gated to 3.10.1 in `e2e_tests/helpers/versionGates.ts`.
*   `e2e_tests/pages/amazonRds.page.ts`, `e2e_tests/pages/dashboards/mysql/mysqlAmazonAuroraDetails.ts`, `e2e_tests/fixtures/pmmTest.ts`, `e2e_tests/testdata/remoteInstances.ts`.

## Verification and Acceptance Criteria

"Met" names the code and tests that cover a criterion; "live check pending" means it still needs a run against real RDS instances.

| # | Criterion | Status |
|---|---|---|
| 1 | Aurora Details opened without URL variables lists the Aurora MySQL services only, and its panels have data except the rows named as conditional. | Met: PMM-T2505. |
| 2 | The page lists an Aurora MySQL instance under its Aurora cluster, with region, engine, "1 / 1", "1 writer", role, Up, and a new-tab link to Aurora Details. | Met: PMM-T2504 and UI tests. |
| 3 | Grouping: Aurora cluster, Multi-AZ DB cluster, replication group (cross-region and cascaded), standalone instance, "AWS info unavailable" per region and engine. | Met in UI unit tests. **Live check pending** for plain RDS standalone and read replica; Multi-AZ DB cluster not checked live. |
| 4 | Role per engine: Aurora MySQL, MySQL and MariaDB, PostgreSQL and Aurora PostgreSQL. | Met in UI unit tests. **Live check pending** for an Aurora PostgreSQL reader and a plain RDS replica; Aurora failover not checked live. |
| 5 | The menu shows only when an RDS Node exists, for viewers too. | Met: navigation tests, pmm-managed and API tests for `nodes:getTypes`. |
| 6 | rds_exporter series carry the Node's shared `environment`, `cluster` and `replication_set`, so an LBAC role filtering on them sees RDS metrics; the labels follow Service changes. | Met in pmm-managed unit tests (`rds_test.go`, `services_test.go`). |
| 7 | Alerts: firing, unsilenced, matched by `service_name` or `node_name`; unknown until silences load; links to rule and Alert groups. | Met in UI tests. |
| 8 | A failed optional query blanks only its values; a failed `up` or `info` query shows an error. | Met in UI tests. |
| 9 | Search and filters survive a reload through URL parameters. | Met in UI tests. |
| 10 | Cluster storage per Aurora cluster, `max` not `sum`; legacy `aurora` engine included. | Met in rds_exporter and UI tests. |
| 11 | 48 CloudWatch calls per Aurora instance and 47 per plain RDS instance; no extra `DescribeDBInstances`. | Met by the metric list and the shared refresh; `rds_exporter_requests_total` not compared live. |
| 12 | `node_filesystem_*` on RDS nodes has an empty `fstype`, and Disk Space shows data. | Met in rds_exporter golden tests (Aurora and plain RDS recordings). **Live check pending** on plain RDS. |
| 13 | CPU Saturation shows data on RDS nodes with Enhanced Monitoring. | Dashboard change. **Live check pending** on plain RDS. |
| 14 | No regression on plain RDS MySQL and PostgreSQL. | **Live check pending.** |
| 15 | Old pmm-client with new server: instances under "AWS info unavailable". | Met in UI unit tests. |

Pending live check, on a Feature Build with the rds_exporter and pmm branches on a CHAOS VM: a plain RDS standalone instance and read replica, and an Aurora PostgreSQL cluster with a reader. PMM-T2504 and PMM-T2505 run in pmm-qa `@instances` against the same build.

--------------------------------------------------------------------------------

*Drafted with EGM; updated to the as-built design*
