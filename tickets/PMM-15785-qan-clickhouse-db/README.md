# QAN database consistency across ClickHouse replicas

- **Ticket:** [PMM-15785](https://perconadev.atlassian.net/browse/PMM-15785), under epic [PMM-14381](https://perconadev.atlassian.net/browse/PMM-14381).
- **Status:** design, in review.
- **Related:** [PMM-14779](https://perconadev.atlassian.net/browse/PMM-14779) (same missing-database state at install, fixed in 3.6.0).
- **Repos touched:** percona/pmm (qan-api2, alert template, HA dashboard), percona/percona-helm-charts (`wait-for-clickhouse`, `pmm-backup.sh`), pmm-qa (HA tests).

| Path | Content |
|---|---|
| [spec.md](spec.md) | Problem (install race, qan-api2 recreate, restore), lab constraints, design (prevent, heal, flag, repair, backup/restore), tests T1–T12, decisions D1–D16 |
