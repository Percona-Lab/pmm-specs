# Aurora monitoring in PMM (PMM-15868), revision 2: Release 1 Aurora MySQL, Release 2 Aurora PostgreSQL

* **Author:** Tibi (tibor.korocz@percona.com)
* **Date:** 2026-11-04

## Overview

PMM treats Aurora instances as plain RDS instances. MySQL Amazon Aurora Details is empty unless `var-service_name` is in the URL. Cluster storage is never collected, and no dashboard groups instances by AWS cluster ([research.md](research.md)). The users are DBAs and SREs who add Aurora instances through RDS discovery.

Revision 2, confirmed by the product owner:

* **Release 1, Aurora MySQL:**
  1. rds_exporter takes `DBClusterIdentifier` and `Engine` from its existing `DescribeDBInstances` call and publishes one info series per instance. Discovery, its API, the add form and inventory labels stay unchanged.
  2. rds_exporter fetches cluster storage and IOPS once per cluster per process, and drops the three `Volume*` metrics from the per-instance list.
  3. A new overview groups instances by AWS cluster through the info series. It shows instance count, up/down and health, summed QPS and storage, with links to alerts and advisors.
  4. MySQL Amazon Aurora Details gets targeted fixes and new rows. Its uid and panel titles stay.
* **Release 2:** Aurora PostgreSQL, found through the engine label. Role comes from live read-only metrics. Environment stays a field users type.
* **Constraints:** keep it small. Never change labels on instances already added.

**How this brief was produced:** six reviewers read research.md and the code. Their lenses were cost and architecture, observability, YAGNI, UX, migration, and maintainability. The synthesizer re-read every reference the conclusions rest on.

* Path prefixes: `rds:` is percona/rds_exporter at `24b256b`, `pmm:` is percona/pmm, `grafana:` is percona/grafana, `pgexp:` is percona/postgres_exporter.
* "Reported" means a reviewer cited it and the synthesizer did not re-read it. "Unverified" means nobody checked it.

**Bottom line:**

* Revision 2 needs no inventory, proto, UI or database change, edits no labels, and needs no version gate.
* Its weakest point is item 1 as written:
  * The 5-minute refresh it relies on exists only on the Enhanced Monitoring path.
  * An overview whose rows come from the info series silently drops every instance that has no current rds_exporter.
* Item 2 saves about 6% of AWS requests per instance, and nothing on a single-instance cluster. Its value is the storage data.
* The dashboard fixes (item 4) are low-risk and can ship alone.

## Analysis

Findings are ordered from weakest point to smallest.

### 1. The 5-minute lookup does not reach the code that would publish the info series (Blocker, all six lenses)

**What the code does (verified):**

* **At start:** `sessions.New` calls `DescribeDBInstances` once per region and access key, and keeps only `ResourceID` and `MonitoringInterval` (`rds:sessions/sessions.go:49-54,88-91,136-151`).
  * An instance the lookup cannot resolve is dropped until the process restarts. Only an error is logged (`:137-140,153-164`).
* **The 5-minute refresh:** it lives only in the Enhanced Monitoring scraper (`rds:enhanced/scraper.go:25,1174-1235`).
  * It first runs 5 minutes after start (`:214`) and updates a private copy (`:404-406`).
  * That scraper covers only instances with enhanced metrics on (`rds:enhanced/collector.go:184-196,217-238`).
* **`/basic`:** it skips instances with basic metrics off. Each scrape waits for 50 CloudWatch calls per instance (`rds:basic/collector.go:62-84`, `rds:basic/scraper.go:77-92`), within a 54 s timeout (`pmm:managed/services/victoriametrics/scrape_configs.go:42-48,567`).

So an info series on `/basic` disappears when CloudWatch is slow, and one on `/enhanced` misses instances with enhanced metrics off.

**Recommendation (five lenses):**

* Read the cluster ID and engine once at start, into `sessions.Instance`.
  * Neither value changes while the instance exists (AWS behaviour, unverified).
  * pmm-agent restarts rds_exporter on any config change (`pmm:agent/agents/supervisor/supervisor.go:729-733`), so the lookup reruns whenever an instance is added under the same credentials (inferred).
* Do not share the enhanced refresh state with `/basic`. It is locked state in a 1,300-line file, for values that do not change.
* Publish the series from memory, for every resolved instance, ignoring the basic and enhanced switches.
* Use exactly one endpoint. Two endpoints give each node two series, and `group_left` joins fail with many-to-many errors.

### 2. An overview built from the info series loses instances silently (Blocker, four lenses)

**An Aurora instance has no info series when:**

* it was added without rds_exporter (`pmm:managed/services/management/rds.go:341`) or as plain remote MySQL;
* its rds_exporter runs on a client pmm-agent that has not been upgraded. The server's agent is only the default (`rds.go:293-296`);
* the start-up lookup failed (finding 1).

**Effect:**

* If rows come from the info series, these instances vanish, and counts and QPS come out low.
* If rds_exporter and mysqld_exporter share a pmm-agent that goes down, the instance disappears instead of showing as down (inferred).

**Requirements:**

* Build the rows from `mysql_up` and left-join the info series on `node_id`.
  * `instance`, `agent_id` and `job` differ between the two sides (reported: `scrape_configs.go:165`).
* Put instances that have no info series into an "AWS cluster unknown" group.
  * Discovery maps Aurora to plain MySQL (`rds.go:59`), so separate them from plain RDS by the presence of `mysql_global_status_auroradb_commits`, which works on Aurora MySQL 3 (research.md).
* Keep rows over a lookback, and show a missing sample as down.

### 3. Label names collide with PMM's `cluster` label and with user labels (Major, all six lenses)

**What the code does:**

* `cluster` is a service label that users type, and dropdowns filter on it (`pmm:dashboards/dashboards/MySQL/MySQL_Amazon_Aurora_Details.json:1066-1074`).
* rds_exporter series carry node labels, including custom labels from the add form (`pmm:managed/services/agents/rds.go:49-61`; `pmm:managed/services/management/rds.go:317-325`).
* Config labels overwrite the exporter's own labels (`rds:basic/scraper.go:41-51`).

**Effects:**

* A user label can overwrite an info label named `cluster` or `engine`.
* A `group_left(cluster)` join would replace the value a user typed.

**Requirements:**

* Use distinct names, for example `aws_cluster_id` and `aws_engine`, set after PMM labels so AWS values win.
* The PRD states that the info series owns AWS topology and the `cluster` label stays the user's. Nothing copies one into the other: changing `cluster` removes scheduled backups (research.md).

### 4. The cluster ID is not a unique key, and cluster series have no owner (Major, five lenses)

* **Account scope:** DB identifiers are unique only within one AWS account (rds_exporter's own comment, `rds:enhanced/scraper.go:61-64`). Same-named clusters in two accounts would merge into one row.
* **Duplicate copies:** PMM runs one rds_exporter per pmm-agent per credential identity (`pmm:managed/services/agents/state.go:393-403,427-438`).
  * A cluster split across processes is fetched once per process.
  * With `honor_labels`, the copies differ only by `job` (`scrape_configs.go:240-247`).
* **Label set:** per-instance labels do not fit a cluster series. Borrowing one member's labels changes the series when that member is removed.
* **Non-Aurora clusters:** RDS Multi-AZ DB clusters also set `DBClusterIdentifier` (unverified).

**Requirements:**

* Label cluster series with region, account and cluster ID only. Reading the account from `DBInstanceArn` is unverified.
* Aggregate with `max by`, never `sum`.
* Fetch only for `aurora-*` engines.

### 5. The request saving is small, and nothing uses IOPS (Major, three lenses)

**Arithmetic** (50 metrics in `rds:basic/metrics.go`, 60 s scrape, $0.01 per 1,000 requests, price unverified):

* **Today:** 72,000 calls per instance per day, or about $21.60 a month.
* **Dropping 3 metrics:** 6% fewer calls per instance.
* **Adding 3 per cluster per process:**
  * A 3-instance cluster ends about 4% lower.
  * A single-instance cluster, the QA setup, saves nothing (47 + 3 = 50).
* **Unchanged:** all 50 × N calls start at the same moment (`rds:basic/collector.go:72-83`, `rds:basic/scraper.go:81-91`). About 8 instances in one region could hit a 400 requests/s quota in one burst (quota unverified).

**Further points:**

* No panel uses `VolumeReadIOPs` or `VolumeWriteIOPs`, and whether they are counts or rates is unverified.
* The fetch reuses a 10-minute window ending 10 minutes ago, and skips empty answers silently (`rds:basic/scraper.go:17-21,95-118`).
  * How often AWS publishes `VolumeBytesUsed` is unverified. If it is less often than every 10 minutes, the panel blinks empty.
* **YAGNI lens alternative:** for `aurora-*` engines, each instance fetches `VolumeBytesUsed` alone with the cluster dimension.
  * This is one call, with no grouping state.
  * Each Aurora instance makes 2 fewer calls.
* **Maintainability lens:** if per-cluster grouping stays, use a pure function on each scrape, with no cache and no timer.

**Requirement:** don't present item 2 as a cost fix. Measure it with `rds_exporter_requests_total` (`rds:client/transport.go:31-34`).

### 6. Failures look the same as an old client (Major, observability lens)

* rds_exporter has no build-info series.
* `rds_exporter_requests_total` has no labels (`rds:client/transport.go:31-38`).
* CloudWatch errors are only logged (`rds:basic/scraper.go:87-89`), and `up` stays 1.

So "pmm-client too old", "AccessDenied", "throttled" and "dropped at start" all render as "No data".

**Options:**

* A cheap `rds_exporter_build_info{version}` series.
* An error counter by AWS operation and code, which adds more scope.

No other lens raised this, and it competes with "keep it simple" (D6).

### 7. Overview columns invite misreading (Major, three lenses)

* **Instance count:** counts instances added to PMM, not cluster members. The IAM policy lacks `DescribeDBClusters` (research.md). Call it "Monitored instances".
* **Up/down:** means "the exporter can connect".
  * `pg_up` is 0 only when every DSN fails to connect, and stays 1 when the connection semaphore can't be acquired (`pgexp:cmd/postgres_exporter/postgres_exporter.go:761-787`).
  * `mysql_up` was not checked.
  * A down agent produces no sample, not 0.
* **Health:** not defined apart from up/down. Define it or drop it.
* **QPS:** PostgreSQL has none; PMM uses transaction commits (reported). Label throughput per engine and never add the engines together.
* **Freshness differs:**
  * Up/down and QPS are 5 s old (`pmm:managed/models/settings.go:237-239`).
  * Role is up to 60 s old.
  * Storage is about 10 minutes behind but stamped with scrape time (`rds:basic/scraper.go:127-131`).
  * State source and lag per column.

### 8. The Details fix can recreate the same breakage, and new rows have no limit (Major, four lenses)

**Variables:**

* Both variables use the missing counter: `service_name` (`MySQL_Amazon_Aurora_Details.json:982-990`) and `node_name` (`:1011-1020`). research.md mentions only the first.
* A single counter or the info series (finding 2) would invite the same failure.
* Use `mysql_global_status_auroradb_commits`, or a `{__name__=~"…"}` union as at `:1039-1047`.

**What to keep:**

* the uid (`:1288`);
* the file path, which `pmm:dashboards/pmm-app/src/plugin.json:66-70` registers;
* the variable names;
* the panel ids used by `viewPanel` links (reported).

**New rows:**

* There are about 130 counters and 36 CloudWatch metrics to choose from.
* Many repeat existing panels with 10-minute-old data, for example CloudWatch commit latency against `:157`.
* Prefer swapping missing counters for collected CloudWatch metrics, such as Deadlocks (`rds:basic/metrics.go:100-103`).
* Name the rows in the PRD.

**QA test:** PMM-T1295 fails on empty panels (research.md). Rows that are empty on clusters with no reader (ACU, write forwarding, parallel query, replica lag) would fail it. pmm-qa was not read.

### 9. Users cannot find either dashboard (Major, two lenses)

* **No menu entry:** no menu links `mysql-amazonaurora`.
  * Neither `pmm:ui/apps/pmm/src/contexts/navigation/navigation.constants.ts` nor percona/grafana `public/app/percona/` mentions Aurora (searched).
  * Users reach it only through search. research.md's "opened from the menu" should read "opened from search".
* **Inventory link:** the Inventory "Dashboard" action always opens `<type>-instance-summary` (`grafana:public/app/percona/shared/helpers/getDashboardLinkForService.ts:3-4`).
* **Requirement:**
  * Add an overview menu entry under MySQL, and in Release 2 under PostgreSQL too.
  * Overview rows link to Details with `var-service_name`.

### 10. The role signal is untested, and Release 2 has two Aurora detectors (Major, all six lenses)

**Role signal:**

* No QA cluster had a reader, so reader values are inferred (research.md).
* At 60 s resolution, a failover can show zero or two writers for up to a minute (inferred).
* `pg_replication_is_replica` exists, but its collector returns early on Aurora. It shares a query with a lag column Aurora cannot compute (`pgexp:collector/pg_replication.go:56-73`).
* `pg_settings_transaction_read_only` reads 1 on a writer whose parameter group sets `default_transaction_read_only` (unverified).

**Two detectors:**

* postgres_exporter caches "Standard" after any detection error (`pgexp:distribution/distribution.go:51-60`).
* The info series could then say `aurora-postgresql` while `query_aurora` entries silently stop.

**Requirements:**

* The info series decides what is Aurora, and postgres_exporter supplies only the role.
* Role comes from a query that runs regardless of detection: a plain `query`, or `is_replica` split from lag.
* A missing role is "unknown", never writer. A writer count other than 1 shows as "changing", not red.
* Test on a reader before the PRD is frozen.

### Smaller findings

* **Dropping `Volume*` metrics is safe:**
  * Nothing in percona/pmm references `aws_rds_volume_*` (searched).
  * The basic scraper doesn't know the engine (`rds:basic/scraper.go:35`), so remove the metrics for every engine.
  * The golden file shows none for RDS MySQL 8.4 or PostgreSQL 16 (reported).
* **Don't drop more metrics from the live counts:** they came from clusters with no reader, so reader-only metrics such as `AuroraReplicaLag` (`rds:basic/metrics.go:15`) looked empty.
* **No version gate needed:** there is no schema, proto or exporter-config change. After a pmm-client downgrade, its instances move to the "unknown" group. State this in the PRD.
* **Missing generator:** `rds:basic/collector.go:16` has a `go:generate` line for a `basic/generate/` folder that doesn't exist. Edit `metrics.go` and `testdata/all.txt` by hand.
* **Test impact:** `rds:basic/collector_test.go:54-95` asserts that a basic-disabled instance produces no series (reported). It changes if the info series ignores the switch.
* **Reuse:** Environments Overview (`pmm:dashboards/dashboards/PMM Health/Environments_Overview.json`, from line 649) already has per-group counts, QPS, a per-service up/down table and the `group_left(environment)` join. Copy it with the AWS cluster label in place of `environment`.

### Where the reviewers disagree

* **Info series endpoint:**
  * `/enhanced`: cost lens.
  * `/basic`: YAGNI lens.
  * Either, as long as it is one endpoint served from memory: maintainability and observability lenses.
* **Cluster storage:**
  * Per cluster per process: the concept.
  * Per instance, `VolumeBytesUsed` only: YAGNI lens.
  * Per-scrape pure grouping: maintainability lens.
* **Account in the key:** required by the cost, observability and maintainability lenses. Only if multiple accounts must be supported: migration lens.
* **Self-metrics:** a Blocker for the observability lens; not raised by the others.
* **Details dropdown source:**
  * The info series, or `mysql_up` filtered through it: maintainability lens.
  * Never the info series: migration and UX lenses.

## Goals vs. Non-Goals

* **In-Scope Goals:**
  * **Release 1, Aurora MySQL:**
    * **rds_exporter, info series:** one series per resolved instance, with distinct labels: cluster ID, engine, and account per D3.
      * It is built from start-up data, ignores the basic and enhanced switches, and is published on one endpoint.
    * **rds_exporter, CloudWatch:** drop the `Volume*` metrics for every engine, and add cluster `VolumeBytesUsed` for `aurora-*` engines (per D4).
    * **Overview:**
      * Rows come from database exporters, grouped by AWS cluster, plus an "AWS cluster unknown" group.
      * Columns: monitored instances, exporter connected (N of M), throughput per engine, storage. Each column states its source and lag.
      * Links to Details, Alerting and Advisors, and a menu entry.
    * **Details:**
      * Fix both variables, SELECT latency, the divide-by-zero guards, Special Command Counters and the missing-counter panels.
      * Add named new rows.
      * Keep the uid, file path, variable names and panel ids.
    * **QA:** PMM-T1295 opens the dashboard without URL variables.
  * **Release 2, Aurora PostgreSQL:**
    * Rows in the same overview.
    * A role signal that does not depend on postgres_exporter detecting Aurora.
    * A details view (D8).
* **Out-of-Scope Non-Goals:**
  * Changes to discovery, its proto, the add form, inventory labels or the PMM database.
  * Alert and advisor counts per cluster.
  * `DescribeDBClusters`, and everything that needs it: true cluster size, the writer flag, Serverless mode, Global Database.
  * Role as a label. Environment from AWS tags.
  * Generic RDS dashboard fixes (Disk Space `fstype`, CPU Saturation, InnoDB I/O, WAL Writes, the Tuples filter), which belong in a separate ticket.
  * Plain RDS monitoring gaps, for example CloudWatch `FreeStorageSpace`, which rds_exporter collects but no dashboard shows. Decided 2026-11-04: this epic stays focused on Aurora; plain RDS goes to a separate ticket.
  * New Aurora alert templates. Converting untouched `graph` panels.

## Key Decisions & Staging for Next Steps

Decided by the product owner on 2026-11-04: the epic stays focused on Aurora. D1 to D3 follow the reviewers' recommendation; the owner raised no objection and may still veto them in review.

| ID | Decision | Reviewers lean towards |
|---|---|---|
| D1 | Info series endpoint and freshness | **Accepted.** One endpoint, from memory, start-up data, every resolved instance. Endpoint open. |
| D2 | Overview row source | **Accepted.** Database exporters, with the info series left-joined on `node_id`, plus an "unknown" group. |
| D3 | Label names and key | **Accepted.** `aws_cluster_id`, `aws_engine`. Region and cluster ID, plus account if multi-account is in scope. |
| D4 | Cluster storage | Storage only, `aurora-*` only, `max by`. Per instance or per cluster per process: open. No IOPS without a panel. |
| D5 | Details dropdown source | A union of mysqld_exporter Aurora counters. |
| D6 | rds_exporter observability | `build_info` at minimum. The error counter is optional. |
| D7 | Role signals | MySQL: `innodb_read_only`. PostgreSQL: a plain `pg_is_in_recovery()` query or a split `is_replica`. Verify on a reader. |
| D8 | Release 2 dashboard form and menu | Open. |

### Staging

0. **Spikes**, on Aurora MySQL 3 and PostgreSQL clusters that each have a reader:
   * the role variables and failover timing;
   * how often `VolumeBytesUsed` is published, and which window fits;
   * whether IOPS is a count or a rate;
   * whether Multi-AZ DB clusters set `DBClusterIdentifier`;
   * whether the account can be read from `DBInstanceArn`;
   * what PMM-T1295 asserts.
1. **Dashboard-only, in any server release:** the Details fixes, the named rows and the PMM-T1295 change.
2. **rds_exporter, shipped with pmm-client:** the info series, the `Volume*` removal, cluster storage and the D6 metrics.
3. **Server release:** the overview, its menu entry and the storage panels. Clients that are not upgraded land in "unknown".
4. **Release 2**, under the same rules.

### Constraints to carry into the draft

* No new IAM permission.
* No PMM database, proto or UI change.
* No label changes on existing instances.
* No dropdown or up/down cell depends on a metric this epic adds.
* Keep the dashboard uid `mysql-amazonaurora`.
