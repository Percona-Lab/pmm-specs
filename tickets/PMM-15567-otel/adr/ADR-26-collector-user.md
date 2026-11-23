# ADR-26: The collector's user

- Status: Proposed. Supersedes ADR-08 once accepted: it changes ADR-08's choice of user and keeps its allow-list rules.
- Date: 2026-11-17
- Tickets: PMM-15567, PMM-15572, PMM-15577, PMM-15591

## Context

- ADR-08 runs the collector as the non-root `pmm-agent` user when pmm-agent runs as root, and checks paths against an allow-list on the node.
- The client packages give that user the whole install tree: `build/packages/deb/postinst:12` and `build/packages/rpm/client/pmm-client.spec:66,215` run `chown -R pmm-agent:pmm-agent /usr/local/percona/pmm`. `pmm-agent.service` has no `User=`, so root runs `pmm-agent` and the exporters from a tree that `pmm-agent` can write. A compromised collector running as `pmm-agent` could replace `bin/pmm-agent` and get root on the next restart (review of 2026-11-13 on Percona-Lab/pmm-specs#9).
- PMM is moving pmm-agent itself to a non-root user.

## Options

1. Keep ADR-08, and make `bin/`, `exporters/`, `tools/` and `config/` root-owned in the packages.
2. Run the collector as a dedicated user that owns only its data directory.
3. Run the collector under pmm-agent's own user, as the exporters run.

## Decision

Option 3 (D35).

- The collector runs under pmm-agent's user, with no credential switch: root in today's packages, uid 1002 in the Docker image, and the non-root user pmm-agent moves to later.
- ADR-08's rules on what the collector may read stay as they are:
  - `pmm-agent.yaml` holds the allow-list: `log-sources.allowed-paths`, default `["/var/log"]`, and `log-sources.allowed-journald-units`, default empty. The server can't change it.
  - Symlinks are resolved before the check, and paths containing `..` are rejected.
  - Database log paths that pmm-agent discovered itself (ADR-19) are accepted outside the allow-list; paths the server merely labels as discovered are not.
- Files the collector opens later, through a glob or a rotation pattern, are checked when read: a record from a file that resolves outside the source's directory and the allow-list keeps only a fixed "blocked" body (plan 02, Task 6).
- The packages still add `pmm-agent` to `systemd-journal`, and to `adm` on Debian and Ubuntu, for when pmm-agent runs as that user.

## Consequences

- While pmm-agent runs as root, the collector runs as root. It parses log content that database users can influence, with full privileges. The allow-list, checked when the config is rendered, and the read-time guard are the only limits on what it reads and ships. The threat model (PMM-15591) records this.
- A compromised collector has pmm-agent's privileges: its binaries, its configuration, and the exporter processes, with the database credentials they hold [I]. A compromised exporter has the same today.
- Running as root, the collector reads every log a database reports, on every OS, so packaged installs need no permission step. When pmm-agent runs as a non-root user, a log its groups can't read needs one documented command per database and OS (D30).
- The supervisor starts the collector as it starts an exporter: no per-process credential code.
- PMM-15572's acceptance criterion "never as root" no longer holds, and the ticket is updated.
