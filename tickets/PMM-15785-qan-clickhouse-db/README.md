# QAN database consistency across ClickHouse replicas

- **Ticket:** [PMM-15785](https://perconadev.atlassian.net/browse/PMM-15785), under epic [PMM-14381](https://perconadev.atlassian.net/browse/PMM-14381).
- **Status:** spec and plans in review.
- **Related:** [PMM-14779](https://perconadev.atlassian.net/browse/PMM-14779) (same missing-database state at install, fixed in 3.6.0).
- **Repos touched:** percona/pmm (qan-api2), percona/percona-helm-charts (`pmm-backup.sh`), pmm-qa (HA tests).

| Path | Content |
|---|---|
| [spec.md](spec.md) | Problem (install race, qan-api2 recreate, writes moving to a stray copy, restore), lab constraints, design (fix the race, keep every node on one `pmm`, backup and restore), tests T1–T9, decisions D1–D13 |
| [plans/00-roadmap.md](plans/00-roadmap.md) | Order of plans 01–03 and the shared contract (package, metrics, SQL, manifest fields) |
| [plans/01-qan-api2.md](plans/01-qan-api2.md) | qan-api2: three-replica test cluster, node inspection, safe creation, `Converge` in the HA leader, metrics (percona/pmm) |
| [plans/02-pmm-backup.md](plans/02-pmm-backup.md) | `pmm-backup.sh`: backup from the pod with the most rows, restore that brings ClickHouse to one `pmm` first, verification (percona/percona-helm-charts) |
| [plans/03-ha-tests.md](plans/03-ha-tests.md) | T1–T9 as automated HA tests (percona/pmm-qa) |
