# ADR-25: Default-off fallback for 3.12.0

- Status: Proposed. Amends ADR-12 for the 3.12.0 release only; ADR-12 stays in force otherwise.
- Date: 2026-11-05
- Tickets: PMM-15567, PMM-15592

## Context

- ADR-12 (Accepted) turns OTEL on by default for new installs and on upgrade, on every ClickHouse profile. It makes the capacity test (PMM-15592) a release blocker, so a failed or unfinished test holds the release.
- D25 targets the Technical Preview at 3.12.0 (due 14 January 2027). On 2026-11-05, PMM-15592 was unassigned and not started.
- Holding 3.12.0 for an unproven capacity test, or turning a Technical Preview on everywhere without one, are both poor outcomes.

## Options

1. Keep ADR-12 as it is: the release waits for PMM-15592.
2. A go/no-go at 3.12.0 code freeze: if PMM-15592 has passed, ship on by default as ADR-12 says; if not, ship 3.12.0 with OTEL off by default, opt-in.
3. Off by default in 3.12.0 regardless of the test.

## Decision

Option 2. If PMM-15592 hasn't passed by 3.12.0 code freeze, these flip for 3.12.0:
- `OtelCollectorEnabledDefault = false` in `managed/models/settings.go`;
- the pmm-ha chart's `otel.enabled: false`, because the chart renders `PMM_ENABLE_OTEL` and that overrides the setting;
- the tests that assert the default: plan 01's `TestSettings/otel_defaults_on_upgrade`, its settings api-test, and plan 01 Review Focus 1;
- the release note and the docs, which then say "off by default; turn it on in Settings → OTEL, with `PMM_ENABLE_OTEL=true`, or with the Helm value".

Everything else stays: the settings, the API, the explorer, and the safeguards of ADR-05. An Admin turns OTEL on with no restart (ADR-12).

## Consequences

- 3.12.0 ships on time either way.
- With the fallback, fewer installs try the Technical Preview, and its problems surface later.
- An install that never changed the setting picks up the default of the release it runs: `collector_enabled` is a `*bool` that stays unset until an Admin sets it, and `IsOtelCollectorEnabled()` falls back to the default, as `IsAlertingEnabled()` does today (`managed/models/settings.go:136-141`). Once PMM-15592 passes, a later release flips the default back to on, and ADR-12 applies unchanged, including on upgrade.
- An Admin who turned OTEL on in 3.12.0 keeps it on after upgrade, because the setting is stored.
