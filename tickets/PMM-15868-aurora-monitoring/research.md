# PMM-15868 Aurora monitoring: findings from a live check

Epic: [PMM-15868](https://perconadev.atlassian.net/browse/PMM-15868).
Checked on 2026-11-04 on a PMM 3.10.1 dev build (dashboards identical to percona/pmm `main` at `5a5165ffe`),
with three Aurora instances from the QA AWS account added through RDS discovery:
two Aurora MySQL 3 instances (MySQL 8.0.42) and one Aurora PostgreSQL 15.15 instance.
Each Aurora cluster has a single writer and no readers. Aurora MySQL had light load (about 19 queries/s); Aurora PostgreSQL had none.
Method: every Prometheus panel query on 29 dashboards was evaluated through `/prometheus/api/v1/query_range`
with dashboard variables resolved as Grafana does, plus screenshots of the Aurora dashboard.

"Verified" means seen in code or in live data. "Inferred" means reasoned, not observed.

## MySQL Amazon Aurora Details dashboard

File: `percona/pmm` `dashboards/dashboards/MySQL/MySQL_Amazon_Aurora_Details.json` (uid `mysql-amazonaurora`), 6 panels of the old `graph` type.

| Item | State | Cause (verified) |
|---|---|---|
| Service and node dropdowns | Empty, so every panel shows "No data" when the dashboard is opened without URL variables (no PMM menu links to it; users reach it through search) | Both are built from `mysql_global_status_auroradb_thread_deadlocks`, which Aurora MySQL 3 does not report |
| With `var-service_name` in the URL | Grafana keeps the value; the 6 panels draw | |
| Transaction Commits | Works | |
| Load | Works | |
| Memory Used | Partial | `aurora_lockmgr_memory_used` present; `aurora_dict_sys_mem_size` missing |
| Statement Latency | Only INSERT draws | SELECT formula adds `qcache_hits`, absent on MySQL 8.0; UPDATE, DELETE, DDL divide by zero when idle (PMM-6655) |
| Special Command Counters | Wrong | `avg by (service_name)` averages the 4 commands into one unlabelled line |
| Problems | Partial | `auroradb_thread_deadlocks` and `aurora_missing_history_on_replica_incidents` missing; `aurora_reserved_mem_exceeded_incidents` present |

QA test PMM-T1295 passes because it opens the dashboard with `service_name` in the URL and only fails on fully empty panels.

## Data collected but not shown

- rds_exporter collects 36 CloudWatch metrics per Aurora MySQL instance and 19 per Aurora PostgreSQL instance.
  Dashboards use 4 `aws_rds_*` metrics in total (read and write latency, CPU credit usage, binlog disk usage).
  Unused for Aurora MySQL: commit latency and throughput, DML/DDL/SELECT/INSERT/UPDATE/DELETE latency and throughput,
  deadlocks, blocked transactions, buffer cache hit ratio, free local storage, binlog replica lag, active transactions, login failures.
- mysqld_exporter collects about 130 `mysql_global_status_aurora*` counters on Aurora MySQL 3, unused:
  write forwarding (`aurora_fwd_*`), parallel query (`aurora_pq_*`), `aurora_serverless_current_acu`/`min_acu`/`max_acu`,
  temp-table RAM, `aurora_thread_pool_thread_count`, `aurora_write_throttling_current_status`.
- Enhanced Monitoring OS metrics (`rdsosmetrics_*`, some `node_*`) arrive for all three instances.
- No `aws_rds_volume_*` series appeared. AWS publishes volume size and volume IOPS per cluster, and rds_exporter queries CloudWatch per instance only (verified, see the rds_exporter section).

## Generic dashboards on Aurora nodes

- Disk Space is empty on every summary dashboard: rds_exporter puts the device name into the `fstype` label
  (`oscar--ephmeral--volume-group-...`), and the panels filter `fstype=~"(ext.|xfs|vfat|)"`.
- CPU Saturation is empty: RDS nodes report `node_cpu_average`, not `node_cpu_seconds_total`.
- MySQL Instances Overview: 6 InnoDB data I/O panels are empty (InnoDB data reads, writes, fsyncs read 0 on Aurora); 3 query-cache panels are empty (as on any MySQL 8.0).
- PostgreSQL: WAL Writes is empty on Aurora (replication collectors skipped, PMM-14527). The Tuples panel's "Fetched" line filters `instance=~"$node_name"`, broken for every PostgreSQL service, not only Aurora.

## Inventory, labels and discovery

- Discovery (`percona/pmm` `managed/services/management/rds.go`, `DiscoverRDS`) calls `DescribeDBInstances`
  and keeps 8 fields: region, AZ, instance ID, instance class, address, port, engine, engine version (lines 220-229).
  `aurora-mysql` and `aurora-postgresql` are mapped to the plain MySQL and PostgreSQL engines (lines 59 and 63).
- The SDK type `types.DBInstance` (aws-sdk-go-v2 `service/rds` v1.131.1) also carries `DBClusterIdentifier`,
  `TagList`, `PromotionTier`, `MonitoringInterval`, `PerformanceInsightsEnabled`, and more. `DBClusterIdentifier` is not referenced anywhere in `managed/` or `api/`.
- Writer/reader flag (`IsClusterWriter`), Serverless mode, Global Database and reader endpoint are only in `DescribeDBClusters`.
  PMM's documented IAM policy grants `rds:DescribeDBInstances`, `cloudwatch:GetMetricStatistics`, `cloudwatch:ListMetrics` and RDSOSMetrics log reads, not `rds:DescribeDBClusters`
  (`documentation/docs/install-pmm/install-pmm-client/connect-database/aws.md`).
- Discovery response proto: `api/management/v1/rds.proto` `DiscoverRDSInstance` (fields 1-8). The add request already has `environment`, `cluster` and `custom_labels`.
- The add-RDS UI lives in `percona/grafana` `public/app/percona/add-instance/` (discovery list in `components/Discovery/`, form starting values in `components/AddRemoteInstance/AddRemoteInstance.tools.tsx`).
- Live labels on Aurora mysqld_exporter and postgres_exporter series today: `region`, `az`, `node_name`, `service_name`, `node_type`, `service_type`; `cluster` and `environment` are empty.
- rds_exporter series (`aws_rds_*`, `rdsosmetrics_*`, `node_*`) get node and agent labels only (`managed/services/agents/rds.go`, `models.MergeLabels(node, nil, agent)`), so they never carry the service label `cluster`; they join service series through `node_name`.
- Changing a service's cluster label through `ChangeService` removes the backup and restore tasks scheduled for the related services (`api/inventory/v1/services.proto`).
- Live role hints already collected: `mysql_global_variables_innodb_read_only`, `read_only`, `super_read_only` (0 on the writers);
  `pg_settings_transaction_read_only` (0 on the writer). Values on a reader are inferred (1), not observed.
- postgres_exporter (`percona/postgres_exporter`) supports Aurora-only queries through a `query_aurora` key in `queries-*.yml`;
  `queries-mr.yaml` already uses `aurora_replica_status()` for `pg_replication_lag`.
  Aurora detection itself is in `distribution/distribution.go`: it checks once whether the function exists (`to_regproc('aurora_version')`) and caches "Standard" on any error, so a transient error hides Aurora until the exporter restarts.

## rds_exporter (percona/rds_exporter `main` at `24b256b`)

The server under test ships rds_exporter 0.7.5, built 2026-11-04; the binary embeds no revision, so matching it to `main` is likely but not confirmed.

- **Process and config.** PMM runs one rds_exporter per pmm-agent per AWS credential identity (`percona/pmm` `managed/services/agents/state.go`, `groupRDSExporters`).
  Its config lists, per instance, region, instance ID, credentials, the basic/enhanced switches and labels (`config/config.go`).
  The labels are PMM's node and agent labels, without `region` (`percona/pmm` `managed/services/agents/rds.go`, `mergeLabels`). There is no field for a cluster ID.
- **AWS instance lookup.** At start, rds_exporter calls `DescribeDBInstances` for every instance the credentials can see (`sessions/sessions.go`, `InstanceStates`); an instance it cannot resolve there is dropped until the process restarts.
  The Enhanced Monitoring scraper repeats the call every 5 minutes, but only for instances with enhanced metrics on, and keeps the result to itself; `/basic` only uses the start-up result (`enhanced/scraper.go`, `resourceIDRefreshInterval`; `enhanced/collector.go`, `getEnabledInstances`).
  It keeps only `DbiResourceId` and `MonitoringInterval`. The same response carries `DBClusterIdentifier` and `Engine`, so reading them needs no new AWS call or permission.
- **CloudWatch (basic metrics).** On every scrape of `/basic`, it makes one `GetMetricStatistics` call per metric per instance, for 50 metrics, with the `DBInstanceIdentifier` dimension only (`basic/scraper.go`, `basic/metrics.go`).
  It asks for the Average over a 10-minute window that ends 10 minutes ago and keeps the newest datapoint, so CloudWatch values are about 10 minutes old (see PMM-13912).
  A metric with no datapoints is skipped, which is why 36 of the 50 appear for Aurora MySQL and 19 for Aurora PostgreSQL.
  `VolumeBytesUsed`, `VolumeReadIOPs` and `VolumeWriteIOPs` are on the list but never return data for Aurora, because AWS publishes them per cluster; those 3 calls per instance per scrape are wasted.
- **Labels on CloudWatch series.** `region`, `instance` (the DB instance ID) and the PMM labels from the config (`basic/scraper.go`, `NewScraper`).
- **Filesystem labels.** `node_filesystem_*` series set both `device` and `fstype` to the AWS file system name on purpose (`enhanced/metrics.go`, `makeNodeFilesystemMetrics`), which the Disk Space panels' `fstype` filter rejects.

## Alerts and advisors

- `percona/pmm` `managed/data/alerting-templates/` has no Aurora template.
- The Home dashboard shows a "Failed advisors" panel (type `pmm-check-panel`, source in `percona/grafana` `public/app/plugins/panel/pmm-check/`); it fetches every failed check with no filter.
- The advisor metric `pmm_managed_advisor_check_insights` has only `service_type`, `advisor` and `check_name` labels (`managed/services/checks/registry.go`), so it can't be narrowed to Aurora services or clusters.
- The built-in `mysql_down` template groups by `service_id, service_name, node_name`, so its alerts don't carry `cluster`.

## Related Jira

PMM-9191 (Aurora 3 compatibility, On Hold since 2021), PMM-10201 and PMM-13541 (closed as duplicates of PMM-9191),
PMM-6655 (statement latency blanks), PMM-14527 (Aurora PostgreSQL replication collectors skipped, Done in 3.7.0),
PMM-2288 (rds_exporter improvements epic), PMM-3206 and PMM-4350 (CloudWatch request count and cost).
