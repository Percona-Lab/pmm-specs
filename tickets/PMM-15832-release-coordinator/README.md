# PMM release coordinator

- **Ticket:** [PMM-15832](https://perconadev.atlassian.net/browse/PMM-15832).
- **Status:** design for review.
- **Repos touched:** percona/percona-helm-charts (branching only), Percona-Lab/jenkins-pipelines (RC test parameters).

| Path | Content |
|---|---|
| [adr/ADR-01-helm-chart-release-branches.md](adr/ADR-01-helm-chart-release-branches.md) | Helm chart changes either go to `main` (ship now) or to `release-pmm-X.Y.Z` (ship with that PMM release) |

**Marks:** **[V]** means verified by reading the code, the ticket or the pull request; **[I]** means inferred, or taken from upstream documentation, and not run. `#NNN` in the ADRs is a pull request in percona/percona-helm-charts.
