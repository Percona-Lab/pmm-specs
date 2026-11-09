# ADR-25: Default state in 3.12.0

- Status: Proposed. Amends ADR-12 for 3.12.0: upgraded installs stay off, and new installs are on only if the capacity test passes. ADR-12 stays in force otherwise.
- Date: 2026-11-05, revised 2026-11-09
- Tickets: PMM-15567, PMM-15592

## Context

- ADR-12 (Accepted) turns OTEL on by default for new installs and on upgrade, on every ClickHouse profile. It makes the capacity test (PMM-15592) a release blocker, so a failed or unfinished test holds the release.
- D25 targets the Technical Preview at 3.12.0 (due 14 January 2027). On 2026-11-05, PMM-15592 was unassigned and not started.
- A capacity test alone doesn't justify starting a new ingestion workload on running deployments whose operators don't expect it: storage, privacy, external ClickHouse without the `otel_*` users, mixed agent versions and HA behaviour all matter there.

## Options

1. Keep ADR-12: on for new installs and upgrades; the release waits for PMM-15592.
2. A go/no-go for every install: on if PMM-15592 has passed by code freeze, off everywhere if not.
3. Upgrades off; new installs on if PMM-15592 has passed by code freeze, off if not.
4. Off everywhere in 3.12.0, opt-in.

## Decision

Option 3.

- `OtelCollectorEnabledDefault = false` in `managed/models/settings.go`. `collector_enabled` is a `*bool` that stays unset until something sets it, and `IsOtelCollectorEnabled()` falls back to the default, as `IsAlertingEnabled()` does (`managed/models/settings.go:136-141`). An upgraded install therefore stays off until an Admin turns OTEL on.
- **New installs:** when `SetupDB` starts from schema version 0, it stores `collector_enabled = OtelOnForNewInstalls`, a build-time constant. It is `true` if PMM-15592 has passed by 3.12.0 code freeze and `false` if not; that is the only thing the go/no-go flips.
- **pmm-ha chart:** no default for `otel.enabled`. The chart renders `PMM_ENABLE_OTEL` only when the user sets the value, so a chart upgrade can't turn OTEL on behind the operator's back.
- **Tests:** an upgrade with no `otel` key in the stored settings gives OTEL off; a new install stores `OtelOnForNewInstalls` (plan 01, Task 4).
- **Docs and release note:** "on for new installs, off after upgrade; turn it on in Settings → OTEL, with `PMM_ENABLE_OTEL=true`, or with the Helm value".

Everything else stays: the settings, the API, the explorer, and the safeguards of ADR-05. An Admin turns OTEL on with no restart (ADR-12).

Turning OTEL on at runtime is how every upgraded install opts in, so it must work without a restart:
- PMM Server's own collector and its log sources are created on every connect of the server's pmm-agent, whatever the setting, and withheld while OTEL is off (plan 02, Task 8);
- turning OTEL on pushes the collector to that pmm-agent; in HA, each pod's reconcile loop pushes it to its own pod's pmm-agent (plan 01, Task 6b).

## Consequences

- 3.12.0 ships on time whether or not PMM-15592 passes.
- Running deployments get no new workload on upgrade. Fewer installs try the Technical Preview, and its problems surface later.
- A later release can turn OTEL on for upgrades; that needs its own decision, which amends this one.
- An Admin who turned OTEL on keeps it on after any later upgrade, because the setting is stored.
