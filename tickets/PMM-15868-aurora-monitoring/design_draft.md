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

--------------------------------------------------------------------------------

<!-- Later sections (Technical Plan, Alternatives, Detailed Implementation) are added one at a time after this section is approved. -->

*Drafted with EGM*
