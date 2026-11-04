# Aurora monitoring in PMM (PMM-15868): Release 1 Aurora MySQL, Release 2 Aurora PostgreSQL

* **Author:** Tibi (tibor.korocz@percona.com)
* **Date:** 2026-11-04

## Overview

PMM monitors Aurora instances today as if they were plain RDS instances. Discovery maps `aurora-mysql` and `aurora-postgresql` to the plain MySQL and PostgreSQL engines and drops the AWS cluster ID (`pmm:managed/services/management/rds.go:59,63,220-229`). The only Aurora dashboard, MySQL Amazon Aurora Details (uid `mysql-amazonaurora`), shows "No data" when opened from the menu. Its Service dropdown reads a counter that Aurora MySQL 3 does not report, and four of its six panels are wrong or partial. PMM already collects 36 CloudWatch metrics per Aurora MySQL instance and about 130 `mysql_global_status_aurora*` counters, but its dashboards show almost none of them ([research.md](research.md)).

The users are DBAs and SREs who add Aurora instances through RDS discovery and then read PMM dashboards.

The concept, as confirmed by the product owner:

* **Release 1, Aurora MySQL:**
  1. RDS discovery shows each instance's `DBClusterIdentifier`. The add form pre-fills the existing Cluster label with it, and the user can edit it. Instances already added keep their labels.
  2. A new Aurora overview dashboard lists clusters with instance count, up/down, firing alerts, failed advisors and summed queries per second. It links to a rebuilt Aurora MySQL details dashboard that fixes the broken panels and adds panels for metrics already collected.
  3. rds_exporter collects the missing cluster-level storage and I/O from CloudWatch, keyed by the real AWS cluster ID, not the editable label.
* **Release 2, Aurora PostgreSQL:** an Aurora-only detection metric, reader-lag queries and its own details dashboard.
* Environment stays a field users type. Writer/reader role comes from live read-only metrics, not labels.
* **Constraint:** keep it small. The preferred moves are collecting missing metrics, fixing broken panels and adding panels for metrics already collected.

**How this brief was produced:** six independent reviewers read research.md and the code in percona/pmm, percona/grafana and percona/postgres_exporter. Their lenses were architecture and cost, code accuracy and observability, YAGNI, UX, migration and compatibility, and maintainability. The synthesizer then re-read the load-bearing references. percona/rds_exporter was not available, so **every statement about rds_exporter's code is unverified**. Paths use a repository prefix: `pmm:` is percona/pmm, `grafana:` is percona/grafana, and `pgexp:` is percona/postgres_exporter.

**Bottom line:**

* The dashboard fixes and the new panels for metrics PMM already collects carry little risk and can ship on their own.
* As written, the concept leaves three questions open, and their answers decide how big the work is:
  1. Which key does the overview group by?
  2. Where does rds_exporter get the AWS cluster ID?
  3. Where do the per-cluster counts of firing alerts and failed advisors come from?
* The first two depend on rds_exporter code that nobody has read. The third has no data source today.

## Analysis

The findings are ordered from weakest point to smallest issue.

### 1. Two keys for one cluster, and no series carries both (Blocker, raised by all six lenses)

**What the code does today:**

* `cluster` is a Service label only (`pmm:managed/models/service_model.go:121-129`). Node labels have no cluster (`pmm:managed/models/node_model.go:127-137`).
* rds_exporter series get their labels from `models.MergeLabels(node, nil, agent)`. The Service argument is `nil` (`pmm:managed/services/agents/rds.go:49-50`). So `aws_rds_*`, `rdsosmetrics_*` and RDS `node_*` series never carry `cluster`, `service_name` or `environment`, even on new instances that get the pre-fill. They can only be joined to mysqld_exporter and postgres_exporter series through `node_name`.
* On live Aurora series, `cluster` is empty today (research.md, "Inventory, labels and discovery"). The product owner has decided it stays empty for instances already added.
* The pre-fill exists only in the UI. API callers do not get it, and pmm-admin has no RDS add command (a reviewer searched `pmm:admin/`).
* An AWS cluster ID is unique only within one account and region (AWS behaviour, unverified here). PMM monitors several accounts through per-instance keys and role ARNs, and no series carries an account ID.

**What breaks:**

* **An overview grouped by `cluster`:** after the upgrade, every existing Aurora instance falls into one group with an empty name. Queries per second, instance counts and writers from unrelated clusters are added together. If the overview instead filters out empty values, as Environments Overview does for `environment`, it is empty for every existing user. Nothing tells the user why.
* **Storage panels keyed by the AWS ID:** if the label differs from the AWS ID, these panels go blank, show the value twice, or show another cluster's value. The label can differ because it was renamed or mistyped, because two AWS clusters share one label, or because two accounts use the same name.
* **Renaming a label splits history:** edited labels apply only to new series (`pmm:documentation/docs/use/dashboard-inventory.md:120`).
* **Editing the label has side effects outside dashboards:**
  * Setting a new cluster label removes all scheduled backup and restore tasks of the related services (`pmm:api/inventory/v1/services.proto:544`). The Edit page warns about this.
  * Alert threshold overrides can target a cluster label value (`pmm:managed/models/alert_rule_threshold_override_model.go:36,65`), so a rename leaves them orphaned.
  * The concept's "users edit labels by hand" sends users through both of these.

**The options (decision D1):**

* **A. Group by the editable `cluster` label.** Four lenses favour this; it is the smaller change.
  * Attach rds_exporter series with `* on(node_name) group_left(cluster) mysql_up`. The same join pattern already exists (`pmm:dashboards/dashboards/MySQL/MySQL_Instance_Summary.json:422`).
  * Group by `(region, cluster)` to reduce collisions across regions.
  * Show instances with no label in an explicit row that is never summed. Inventory already has wording for this: "Non-clustered services" (`grafana:public/app/percona/inventory/Tabs/Services/Clusters.utils.ts:14`).
* **B. Group by the real AWS ID.** The design lens favours this; it depends on rds_exporter internals that nobody has read.
  * rds_exporter publishes one info series per instance with `node_name`, region, AWS cluster ID and account.
  * The overview groups by that ID and shows the label as a display column, falling back to the label when there is no info series.
  * Instances already added work without label edits.

Either way, the AWS ID must not be emitted under the label name `cluster`. The existing dashboard already filters on PMM's `cluster` label (`pmm:dashboards/dashboards/MySQL/MySQL_Amazon_Aurora_Details.json:1066-1074`).

### 2. The source of the real AWS cluster ID for rds_exporter is not defined (Blocker, five lenses)

**What the code does today:**

* Each instance's rds_exporter config holds only region, instance ID, access keys, role ARN, two disable flags and labels (`pmm:managed/services/agents/rds.go:33-42,94-103`). There is no cluster field.
* PMM stores no cluster ID anywhere:
  * not in the Node model (`node_model.go:52-78`);
  * not in the `AWSOptions` JSONB (`pmm:managed/models/agent_model.go:171-183`);
  * not in `DiscoverRDSInstance` (`pmm:api/management/v1/rds.proto:21-38`);
  * not in `AddRDSServiceParams`, which has only the free-text `cluster` label.
* PMM runs one rds_exporter process per pmm-agent per AWS credential identity (`pmm:managed/services/agents/state.go:393-397`). That pmm-agent is the server's own by default, or a client's pmm-agent when `pmm_agent_id` is set (`pmm:managed/services/management/rds.go:293-296`).

**Path X: PMM passes the ID.** This needs:

* a new discovery field and a UI pass-through;
* a new `AddRDSServiceParams` field (fields 1-38 are used);
* storage, either a JSONB key or a column plus a migration;
* a new exporter config field and a pmm-agent version gate.

Instances already added never get the ID unless PMM backfills it. For role-ARN exporters on client pmm-agents, the server holds no credentials that can call AWS (`rds.proto:45-50` compared with `142-147`), so a backfill is impossible for them. Path X spans three repositories plus storage, which is not a small change.

**Path Y: rds_exporter looks the ID up itself.**

* It reads `DBClusterIdentifier`, `Engine`, and the account from `DBInstanceArn`, from `DescribeDBInstances`. The documented IAM policy already grants that call (`pmm:documentation/docs/install-pmm/install-pmm-client/connect-database/aws.md:39-53`).
* PMM needs no database, proto or UI change on the exporter path.
* Instances already added get cluster metrics once the pmm-agent that runs their rds_exporter is upgraded.
* **Unverified:** whether rds_exporter already calls `DescribeDBInstances`.
* Describe calls are throttled per account, and customers' own tools share that limit (limits unverified). The result should be cached and refreshed every 10 to 15 minutes at most.

All lenses prefer Path Y if a spike confirms it. Reading rds_exporter is the first task.

### 3. "Firing alerts" and "failed advisors" per cluster have no data source (Blocker for the overview as specified, all six lenses)

**Advisors:**

* The only metric is `pmm_managed_advisor_check_insights{service_type, advisor, check_name}`. It has no service or cluster label (`pmm:managed/services/checks/registry.go:39-44`; namespace at `pmm:managed/services/checks/checks.go:68-69`).
* The `pmm-check-panel` source does exist. It is at `grafana:public/app/plugins/panel/pmm-check/`, which corrects research.md ("Alerts and advisors"). It fetches with `CheckService.getAllFailedChecks(undefined, true)` and applies no filter (`Failed.tsx:33`).
* A reviewer reports that the `ListFailedServices` API takes no filter (`pmm:api/advisors/v1/advisors.proto:142`).

**Alerts:**

* Alert rules are Grafana-managed (`pmm:managed/services/alerting/service.go:851`).
* PMM's `grafana.ini` sets only `[unified_alerting] enabled = true` (`pmm:build/ansible/roles/grafana/files/grafana.ini:87-88`). So alert state is not written to VictoriaMetrics as series, and no PMM dashboard reads `ALERTS` or uses an alert-list panel.
* The built-in down template aggregates `max by (service_id, service_name, node_name)` over `pmm_managed_inventory_agents` (`pmm:managed/data/alerting-templates/mysql_down.yml:9`). That drops `cluster`, and the inventory metric has no cluster label anyway.
* `node_high_cpu_load` uses `node_cpu_seconds_total`, which RDS nodes do not report, so it never fires on Aurora. There is no Aurora template.

**What building them would take:** alert-state export, template changes, and either new advisor metric labels or a panel filter. That is new plumbing in pmm-managed and the Grafana fork. A cell showing "0" would read as healthy when it means "not covered".

**Consensus recommendation:** cut both columns from Release 1 and link to the Alerting and Advisors pages instead. Reviewers mention one possible addition: a Grafana alert-list panel on the details dashboard, filtered by `service_name` (unverified that it accepts a dashboard variable).

### 4. Cluster-level CloudWatch series: duplicates and cost (Major, four lenses)

**Duplicates:**

* Instances of one cluster can end up in different exporter processes, through different credentials or different pmm-agents (`state.go:393-404`). Scrape jobs are per exporter and use `honor_labels` (a reviewer reports `pmm:managed/services/victoriametrics/scrape_configs.go:240-253`).
* If each instance fetches its own cluster's metrics, a cluster with N added instances gets N copies of each series. A `sum` then overstates the value N times, and N times the requests go to CloudWatch.

**Cost and quota:**

* The `/basic` endpoint is scraped at the low-resolution interval, 60 s by default (`pmm:managed/models/settings.go:244`). CloudWatch cost is already a tracked complaint (PMM-3206, PMM-4350).
* The design lens estimated volume and cost. It assumes one `GetMetricStatistics` call per metric per scrape and about $0.01 per 1,000 requests; both assumptions are unverified.
  * Today one Aurora MySQL instance makes about 1.56 million requests a month.
  * Four cluster metrics, fetched once per cluster every 300 s, add about 34,560 requests per cluster per month.
  * Fetching them per instance every 60 s costs about 15 times that for a three-instance cluster.
* AWS may publish some cluster volume metrics at coarse granularity (unverified). Polling every 60 s would then return repeated values or gaps.
* Throttling can push the whole `/basic` scrape past its timeout, and then all basic metrics are lost, not only the cluster ones. A `TODO: split by 50 exporters per group` is already open at `state.go:396`.
* Non-Aurora RDS Multi-AZ DB clusters may also set `DBClusterIdentifier` (AWS behaviour, unverified). Keying collection on "has a cluster ID" would then spend calls that return nothing.

**Requirements (all on the rds_exporter side, all unverified against its code):**

* Fetch cluster metrics once per (account, region, cluster ID) in each process.
* Fetch on a timer of 300 s or more, off the scrape path, and serve the cached value.
* Fetch only for `aurora-*` engines, and obey `disable_basic_metrics`.
* Limit the list to the 3 to 5 metrics the dashboard draws.
* Use a distinct label name for the AWS ID.
* Dashboards reduce with `max by` the AWS ID before any `sum`.

The YAGNI lens would cut cluster storage from Release 1 entirely, since the rest of Release 1 stands alone. The other lenses keep it under these rules (decision D3).

### 5. The details dashboard can break the same way again (Major, four lenses)

**Why it broke, and why nobody noticed:**

* The Service and Node dropdowns read `mysql_global_status_auroradb_thread_deadlocks` (`MySQL_Amazon_Aurora_Details.json:982-990,1011-1020`).
* QA test PMM-T1295 hides this by passing `var-service_name` in the URL. The repository's dashboard tests check only cleanup fields and JSON validity (a reviewer reports `pmm:dashboards/misc/test_cleanup_dash.py`).
* No label marks a service as Aurora, because discovery collapses the engine.

**Fix the dropdown so this cannot recur:**

* Build the dropdown from `mysql_up`, which every MySQL service has, filtered by `$environment` and `$cluster`.
* Restrict the list to Aurora by matching a family of counters (for example `{__name__=~"mysql_global_status_aurora.+"}`), not one counter. `auroradb_commits` is known to work on Aurora MySQL 3 (research.md).
* Show a text panel when no Aurora service exists.
* Have QA open the dashboard from the menu, with no URL variables.

**The defects are small expression edits.** The YAGNI lens counts about eight.

* SELECT latency (line 576) adds the `qcache_hits` rate to the latency value; it does not add it to the denominator. On MySQL 8.0 the series is missing, so the whole result is empty.
* DDL, INSERT, UPDATE and DELETE latency need `> 0` on their denominators, as Commit Latency already has (line 157; PMM-6655).
* Special Command Counters uses `avg by (service_name)`. It should be `sum by (service_name, command)` (line 721).
* Remove or replace the metrics Aurora MySQL 3 does not report (lines 449, 841, 850).
* Remove the unused PostgreSQL variables (`database`, `username`, `schema`).

**Compatibility:**

* Keep the uid `mysql-amazonaurora`, which is registered in `pmm:dashboards/pmm-app/src/plugin.json`. Also keep the file path and the `service_name` variable name; the annotations use that name.
* One reviewer reports that pmm-qa tests and a support data-collection script in another Percona repository hard-code the uid and the six panel titles. Those files are outside the listed repositories and were not re-checked.
* PMM-T1295 fails on empty panels. New panels that stay empty on single-writer clusters (reader lag, write forwarding, parallel query, Serverless ACU) would fail it. Put them in collapsed rows, or update the test in the same release.

**Navigation:** the dashboard is not in the menu (`grafana:public/app/percona/shared/components/PerconaBootstrapper/PerconaNavigation/PerconaNavigation.constants.ts:288-344`). The Inventory "Dashboard" action sends Aurora services to `mysql-instance-summary` (`grafana:public/app/percona/shared/helpers/getDashboardLinkForService.ts:3-4`). The overview needs a menu entry, and Release 2 changes where that entry should go (decision D8).

### 6. Writer/reader role from read-only metrics has not been checked on a reader (Major, four lenses)

**What has and has not been observed:**

* No test cluster had a reader. Reader values are inferred, not observed (research.md).
* `global_variables` is scraped at low resolution, 60 s by default. After a failover, the cluster can show zero or two writers for up to one interval (inferred).
* A parameter group can set `read_only`. Only `innodb_read_only` follows the instance role on Aurora MySQL (unverified).
* Global Database secondaries legitimately have no writer. PMM cannot tell them apart without `DescribeDBClusters`, which the IAM policy does not grant. Write forwarding and Serverless v2 were not checked.

**PostgreSQL:**

* `pg_settings_transaction_read_only` reflects the exporter's own session. It reads 1 on a writer when `default_transaction_read_only` is on for the monitoring role (unverified on Aurora).
* The alternative, `pg_replication_is_replica`, already exists, but the replication collector returns early on Aurora (`pgexp:collector/pg_replication.go:70-73`). Using it needs a small collector change, which adds scope.

**Requirements:**

* Treat role as information, not health. Show "changing / unknown" when a cluster has a writer count other than 1. Never colour that state red, and never alert on it.
* The panel description states the refresh interval.
* Check reader values on a cluster with at least one reader before the PRD is frozen.

### 7. Instances already added: the cost of relabelling (Major, UX and compatibility lenses)

**How a user edits labels today:**

* One service at a time, through Inventory > Services > Edit (`grafana:public/app/percona/inventory/Tabs/Services/ServicesTable.tsx:60-71`, `grafana:public/app/percona/edit-instance/EditInstance.tsx`).
* Or through `PUT /v1/inventory/services/{service_id}` with an optional `cluster` (`services.proto:469`).
* There is no bulk edit and no pmm-admin command.

**What gets in the way:**

* The Edit page shows the backup-removal warning from finding 1 (`grafana:public/app/percona/edit-instance/EditInstance.messages.ts:18-23`). That can stop users from saving.
* The Edit page does not show the AWS cluster ID, and discovery does not mark instances that are already monitored.

**Without building anything:**

* Add a docs section with the UI path and one `curl` example of the API call.
* Add a release-note line.
* Link to the docs section from the overview's "no Cluster label" row.

Do not build bulk edit.

### 8. Overview column names would mislead (Major, UX, design and observability lenses)

* **Up/down:**
  * `mysql_up` and `pg_up` mean "the exporter can connect". The Inventory tooltip calls the down state "Database is not running."
  * Discovery does not keep the AWS instance status, so PMM cannot tell "stopped in AWS" from "unreachable" from "deleted".
  * Instances whose exporter stops reporting drop out of a count built on `mysql_up`.
  * Readers removed by Aurora Auto Scaling stay in Inventory and show as down indefinitely.
  * Suggested fix: name the column "Reachable by PMM", show it as "N of M", show a separate "No data" state, and add a note about deleted instances.
* **Instance count:** this can only count instances added to PMM, because PMM has no `DescribeDBClusters`. Suggested name: "Instances in PMM".
* **Load:**
  * The existing "Amazon Aurora Load" panel is statement time per second (`MySQL_Amazon_Aurora_Details.json:276-328`), not queries per second.
  * postgres_exporter provides no queries-per-second figure for PostgreSQL. A reviewer reports that the Home dashboard uses `xact_commit + xact_rollback` instead.
  * Suggested fix: name each measure by what it counts.

### 9. Version skew across packages (Major, compatibility and maintainability lenses)

**What ships where:**

* Dashboards ship with PMM Server.
* rds_exporter, postgres_exporter and the `queries-*.yml` files ship with pmm-client.
* A reviewer reports that the server image bundles pmm-client. So the server's own pmm-agent is upgraded with the server, and client pmm-agents are not.

**What can go wrong:**

* A new CLI flag can make an older exporter exit. `pmm:version/features.go:28-30` documents this for node_exporter.
* One rds_exporter process serves every RDS instance of a credential identity, so a crash stops RDS monitoring for that whole group.
* The existing RDS gate withholds the whole exporter from older agents (`pmm:managed/services/agents/rds.go:70-80`). It must not be copied for this feature.

**Rules:**

* No dropdown, overview row or up/down cell may depend on a metric this epic adds.
* Panels that use new metrics state the minimum pmm-client version.
* The percona/grafana UI is built into the server image at a pinned commit. The discovery field and the pre-fill must land in the same release, and the UI must accept a missing field.

### 10. Release 2 risks (Major, four lenses)

**Detection can stick on the wrong answer:**

* postgres_exporter detects Aurora once, with `to_regproc('aurora_version')`, and caches the result per host:port. Any error caches "Standard" (`pgexp:distribution/distribution.go:51-60`).
* A failure when the exporter starts, for example during a failover or reboot, marks an Aurora instance as standard until the process restarts. Its `query_aurora` entries then stop silently.
* Correction to research.md: `query_aurora` does not detect Aurora. It only selects which query runs after detection (`pgexp:cmd/postgres_exporter/queries.go:227-239`).

**The detection metric can be YAML only:**

* An entry with only `query_aurora` emits nothing on standard servers (`pgexp:cmd/postgres_exporter/namespace.go:36-39`).
* The maintainability lens proposes a plain `query` that returns 0 or 1 on every instance. Then "absent" means an old client, 0 means not Aurora and 1 means Aurora.
* Either way, stop caching the detection result after an error.

**Reader lag:**

* The current Aurora `pg_replication_lag` query returns `MAX(replica_lag_in_msec)` across `aurora_replica_status()` on any reader, and 0 on the writer (`pgexp:queries-mr.yaml:6`). So every reader shows the cluster-wide maximum.
* Per-reader lag needs the instance's own row. The function to pick it, `aurora_db_instance_identifier()`, is unverified.
* Add per-reader lag under a new metric name. Do not redefine `pg_replication_lag`, because user alerts may depend on it.

**What already exists, and what older clients see:**

* PostgreSQL Replication Overview reads `pg_replication_lag_seconds`, which the collector skips on Aurora. The YAGNI lens notes that an `or pg_replication_lag` fallback on that dashboard may cover part of the need.
* Clients older than Release 2 lack the new metrics, so the dropdown must not depend on the detection metric.

### 11. Failures in the new collection would be invisible (Major, observability lens)

**Why failures would be invisible:**

* `up` exists per exporter process, not per instance or per cluster.
* The agent status stays RUNNING whatever CloudWatch returns.
* AccessDenied, throttling, a wrong ID and missing datapoints all look the same: "No data".
* There is a precedent. An older exporter accepted a role config, reported RUNNING and scraped nothing (`pmm:managed/services/agents/rds.go:71-73`).

**The minimum:**

* rds_exporter logs each failure at warn level with the AWS error code, rate-limited.
* Panel descriptions name the metric and the exporter version they need.

An error counter and a last-success timestamp per cluster would add scope; decide on them under D10.

### Smaller findings

* **Discovery list readability:**
  * The list is a deprecated basic table with no sorting or filtering. It is sorted by region, then instance ID (`pmm:managed/services/management/rds.go:246-252`).
  * Put the Cluster ID column after Instance ID, and sort by region, cluster, then instance.
  * Consider showing "Aurora MySQL" and "Aurora PostgreSQL" in the Engine column, since the engine is collapsed today.
  * The Cluster form field has no tooltip.
* **Possible side bug:** `getRDSCredentials` copies a fixed list of fields that leaves out `engine`, `engine_version` and `node_model` (`grafana:public/app/percona/add-instance/components/AddRemoteInstance/AddRemoteInstance.tools.tsx:58-72`). Whether RDS nodes added from the UI therefore miss `node_model` is unverified. The pre-fill needs one entry added to this list.
* **Stale comment:** `rds.go:59` calls `aurora-mysql` "MySQL 5.7-compatible Aurora".
* **research.md correction:** the list of labels on "Aurora series" holds for mysqld_exporter and postgres_exporter series. It does not hold for `aws_rds_*` or `rdsosmetrics_*`.
* **Proto change:** adding field 9 to `DiscoverRDSInstance` is additive and passes `buf breaking`.
* **IAM:** no new permission is needed if the design stays on `DescribeDBInstances` and `GetMetricStatistics`. Discovery logs per-region errors only at debug level (`rds.go:205-208,254-257`), so a later `DescribeDBClusters` AccessDenied would be silent.
* **Generic dashboards:**
  * The Disk Space `fstype` filter appears in 24 dashboards.
  * The device rds_exporter reports there is the instance's local temporary volume, not the cluster volume, so a "fixed" Disk Space panel would mislead users.
  * Keep these out of scope. If they are fixed later, fix them in rds_exporter.
* **Panel type:** 34 dashboards still use the old `graph` type. Convert only the panels that are touched anyway.

### Reuse found in the codebase

* Environments Overview "Service Summary" table (`pmm:dashboards/dashboards/PMM Health/Environments_Overview.json`, title at line 1935). It shows per-service up/down and queries per second, with `rdsosmetrics_*` fallbacks. Copy it and replace `environment` with `cluster`.
* MySQL Instances Overview already has a visible Cluster dropdown, a Services count and a Total Current QPS panel. It could serve as the overview through a `var-cluster` link.
* The PXC Galera Cluster Summary pattern: a cluster dropdown that drives a hidden multi-select `service_name`.
* `label_values(mongodb_up{cluster=~"$cluster"}, service_name)` in MongoDB Instance Summary, a pattern for a dropdown that does not depend on one engine-specific counter.
* The postgres_exporter `query_aurora` key, for Aurora-only metrics that need only YAML.

### Where the reviewers disagree

* **Grouping key:**
  * Editable label: the migration, maintainability, UX and YAGNI lenses.
  * Real AWS ID through an rds_exporter info series: the design lens.
  * The observability lens suggests the info series as a join helper under either option.
* **Cluster storage in Release 1:**
  * Cut it: the YAGNI lens, and the design lens if no new CloudWatch spend is acceptable.
  * Keep it under the rules in finding 4: the other lenses.
* **The overview dashboard:**
  * The YAGNI lens would link to MySQL Instances Overview with `var-cluster` instead of building one.
  * The other lenses accept a new overview copied from Service Summary, without the alert and advisor columns.
* **Release 2 dashboard:**
  * The YAGNI lens prefers an Aurora row in PostgreSQL Instance Summary.
  * The maintainability lens prefers a separate dashboard with only Aurora panels, because a row stays empty for non-Aurora users and Grafana cannot hide it.
* **PostgreSQL role signal:**
  * `pg_settings_transaction_read_only`: the concept as written.
  * `pg_replication_is_replica`: the maintainability lens. It needs a collector change.

## Goals vs. Non-Goals

* **In-Scope Goals:**
  * **Release 1, Aurora MySQL:**
    * Fix MySQL Amazon Aurora Details in place: the Service dropdown, statement latency, Special Command Counters, and the Memory and Problems panels. Add an empty-state panel. Keep the uid, file path and `service_name` variable.
    * Add panels for data PMM already collects:
      * from CloudWatch: commit and DML latency and throughput, deadlocks, blocked transactions, buffer cache hit ratio, free local storage, binlog replica lag, active transactions, login failures;
      * from mysqld_exporter: write forwarding, parallel query, Serverless ACU, write throttling and thread pool counters.
      * Put panels that stay empty on single-writer clusters in collapsed rows.
    * Discovery returns `DBClusterIdentifier` as an additive proto field. The add form pre-fills Cluster with it, and the user can edit it. Instances already added are not changed.
    * An Aurora overview listing clusters, with instances in PMM, reachable instances shown as "N of M", and summed queries per second. It has an explicit row for Aurora instances without a Cluster label, and links to the details dashboard and to the Alerting and Advisors pages.
    * Cluster-level storage and I/O from CloudWatch in rds_exporter, if the spike confirms Path Y (decisions D2 and D3).
    * PMM-T1295 opens the dashboard from the menu, with no URL variables.
    * Docs: how to set Cluster on existing instances (UI path and API example), and the CloudWatch request impact.
    * Constraint: no new IAM permission.
  * **Release 2, Aurora PostgreSQL:**
    * An Aurora detection metric, defined in YAML.
    * Per-reader lag under a new metric name.
    * A details dashboard, or Aurora rows in an existing dashboard (decision D8).
    * PostgreSQL rows in the same overview.
    * Role from live metrics.
* **Out-of-Scope Non-Goals:**
  * Per-cluster counts of firing alerts and failed advisors. They would need alert-state export, alert template label changes, and advisor metric labels or a panel filter.
  * Changing the labels of instances already added; a backfill; bulk label edit; a pmm-admin RDS add command.
  * Any use of `DescribeDBClusters`: the writer flag, Serverless mode, Global Database, the reader endpoint, the true cluster member count.
  * Filling Environment from AWS tags.
  * Role as a label.
  * Fixes to generic RDS dashboards: Disk Space `fstype`, CPU Saturation, InnoDB data I/O, PostgreSQL WAL Writes, the Tuples "Fetched" filter. These belong in a separate ticket.
  * New Aurora alert templates.
  * Storing the AWS cluster ID in the PMM database, unless the rds_exporter spike rules out Path Y.
  * Converting `graph` panels the work does not touch.

## Key Decisions & Staging for Next Steps

### Decisions to settle before `/egm-draft`

| ID | Decision | What the reviewers lean towards |
|---|---|---|
| D1 | Overview grouping key | Editable `cluster` label, grouped with `region`, plus an explicit unlabelled row. The AWS ID stays internal to rds_exporter, or appears as display information only. |
| D2 | Source of the AWS cluster ID for rds_exporter | rds_exporter reads it from `DescribeDBInstances` (Path Y). Confirm by reading rds_exporter first. |
| D3 | Contract for cluster-level series, or cut them from Release 1 | If kept: a distinct label name (not `cluster`), one fetch per (account, region, cluster), a timer of 300 s or more, `aurora-*` engines only, obey `disable_basic_metrics`, 3 to 5 metrics, `max by` in dashboards. |
| D4 | Alert and advisor columns | Cut them, and link to the Alerting and Advisors pages. |
| D5 | Rebuild or targeted fix of the details dashboard | Targeted fixes plus new rows. Keep the uid and panel titles, or update pmm-qa in the same release. |
| D6 | Role signal per engine | Aurora MySQL: `innodb_read_only`. Aurora PostgreSQL: open, `pg_settings_transaction_read_only` or `pg_replication_is_replica`. Either way, verify on a cluster with a reader. |
| D7 | Aurora MySQL 2 support | Open. Target Aurora MySQL 3 only, or pair each v2-only counter with its v3 counterpart through `or` and never use it as a dropdown source. |
| D8 | Release 2 dashboard form and menu placement | Open between a separate dashboard and rows in an existing one. One overview for both engines. |
| D9 | Release 2 detection metric | A 0/1 query on every instance, and no caching of the detection result after an error. |
| D10 | Minimum observability for rds_exporter | Warn-level logs with AWS error codes. Self-metrics only if they are cheap. |

### Staging

0. **Spikes, before the PRD:**
   * Read rds_exporter:
     * Does it call `DescribeDBInstances`?
     * Which CloudWatch API does it use?
     * Does it loop over instances or over clusters?
     * How strict is its config parser?
     * How does it handle errors?
     * Does it expose any self-metrics?
   * Stand up an Aurora MySQL 3 cluster and an Aurora PostgreSQL cluster, each with at least one reader. Observe the read-only variables, `pg_is_in_recovery()` and the rows of `aurora_replica_status()`. Check the granularity of AWS cluster volume metrics and whether `aurora_db_instance_identifier()` exists.
1. **Dashboard-only, can ship alone in any server release:** the details dashboard fixes, the new panels for collected metrics, and the PMM-T1295 change.
2. **Server release with percona/grafana moved in step:** the discovery field, pre-fill and Cluster tooltip; the overview and its menu entry; the docs.
3. **rds_exporter cluster metrics, after the spike:**
   * Ships with pmm-client. The server's own pmm-agent gets it on server upgrade.
   * Then add the storage panels to the details dashboard and the overview.
4. **Release 2:** Aurora PostgreSQL, under the same rules.

### Constraints to carry into the draft

* No new IAM permission.
* No PMM database migration in Release 1, unless the D2 spike rules out Path Y.
* Proto changes stay additive.
* No dashboard dropdown, overview row or up/down cell depends on a metric this epic adds.
* Keep the dashboard uid `mysql-amazonaurora`.
* Every claim about rds_exporter stays marked unverified until the spike reads its code.
