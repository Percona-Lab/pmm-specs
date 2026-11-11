# ADR-01: Helm chart changes for a PMM release go to a `release-pmm-X.Y.Z` branch

- Status: Proposed
- Date: 2026-11-11
- Tickets: PMM-15832
- Implemented: not yet. Needs one lint change and a branch protection rule in percona/percona-helm-charts, and the coordinator steps below.

## Context

The `pmm` and `pmm-ha` charts live in percona/percona-helm-charts, a repository PMM shares with the operator teams. CODEOWNERS gives `charts/pmm/` and `charts/pmm-ha/` to `@percona/pmm-review-be`, and everything else to the operator teams. **[V]**

**Merging to `main` is releasing.** `release.yaml` runs on every push to `main` and nowhere else. It runs chart-releaser with `skip_existing: true`, which publishes every chart whose `Chart.yaml` `version` has no release yet, to the Helm repository on `gh-pages` and to `oci://ghcr.io/percona/percona-helm-charts`. **[V]** On pull requests, `ct lint --target-branch "$GITHUB_BASE_REF"` checks `charts/pmm`, and chart-testing fails a changed chart whose version was not increased. **[V]** for the call, **[I]** for the version check (chart-testing's default). `pmm-ha` is excluded from `ct lint`, so nothing enforces its bump. **[V]** So every `pmm` chart PR merged to `main` ships a new chart version on merge.

During a PMM release cycle, chart work comes in two kinds, and today both can only go to `main`:

- Changes that work with the PMM already released, such as ArgoCD support. These can ship now.
- Changes that need the next PMM Server (a new setting, component or image), or that the team wants to ship with it. These must not reach users before PMM X.Y.Z does.

For some changes, ArgoCD support among them, either answer is valid, and the team needs to make that choice for each change.

The release coordinator (PMM-15832, step 4) already ends each release with one chart PR, "pmm and pmm-ha on X.Y.Z". The owners merge it once the GA tag is out and the docs are live, and the post-release tests then install the published chart.

The repository already has precedents. PMM used `release-pmm-3.8.0` and `release-pmm-3.8.1` (merged as percona-helm-charts#859 and #866). The operator teams use `release-psmdb-1.24.0`, `release-pg-3.2.0` and `release-pxc-1.21.0`. `PMM-HA-GA` was a long-lived integration branch: it took about six weeks, with repeated `Merge branch 'main' into PMM-HA-GA` commits, and landed as #927. **[V]**

The PMM HA Jenkins jobs (`pmm3-ha-eks`, `pmm3-ha-rosa`, `pmm3-ha-helm-upgrade-tests`, `pmm3-ha-e2e-tests-gha`, `pmm3-ha-backup-restore-tests`) take a percona-helm-charts branch as a parameter. A branch can therefore be tested before anything is published. **[V]**

## Options

1. **Status quo: everything goes to `main`, and "later" PRs stay open until release day.** Rejected: nothing is integrated until the release. Held PRs conflict with each other, RC testing cannot run them together, and release day turns into several merges, each one a separate chart release.
2. **One long-lived `develop` (or `pmm-next`) branch.** Rejected: the name does not say which release a change ships in. When 3.11.0 is in freeze and 3.12.0 work starts, one branch has to serve two releases. The branch never empties, so it needs back-merges from `main` for good, a cost `PMM-HA-GA` already showed.
3. **Change how the repository publishes**, so that charts ship on a tag or a manual workflow run instead of on merge. Rejected: this changes the release model of the operator charts, which other teams own. `main` would also stop matching what `helm install` gives users.
4. **Merge without a version bump, and publish later by bumping.** Rejected: `ct lint` fails without a bump. Even with that worked around, the next unrelated bump would ship everything that had piled up, which is the opposite of choosing.
5. **One branch per PMM release, `release-pmm-X.Y.Z`, with `main` kept as what is published.**

## Decision

Option 5. These rules apply to `charts/pmm` and `charts/pmm-ha`.

1. **The PR's base branch is the release decision.**
   - Base `main`: the change ships when the PR merges. Use it for chart-only changes that work with the released PMM. Bump the chart's patch `version` (the repository's CONTRIBUTING rule), and leave `appVersion` unchanged.
   - Base `release-pmm-X.Y.Z`: the change ships with PMM X.Y.Z. These PRs change neither `version` nor `appVersion`; the release commit sets both once (rule 4).
   - To change the decision, retarget the PR ("Edit" next to the base branch). For that to stay a one-click change, start feature branches from `main`. Start from the release branch only when the change builds on something that is already there.
2. **Merge to a release branch only what is ready to ship.** A change that is not ready stays an open PR. If a merged change must not ship after all, revert it on the release branch, and re-land it on the next release branch by reverting the revert.
3. **Lifecycle of `release-pmm-X.Y.Z`:**
   - **Create** it from `main`. The coordinator creates `release-pmm-<next>` when it closes the previous release (step 6, where it already moves leftover tickets to the next Jira version). Anyone may create it earlier, named after the Jira fixVersion.
   - **Keep it current** by merging `main` into it, never by rebasing, because other PRs are based on it. Do this after each merge to `main` that touches `charts/pmm*`, and at the latest before RC testing, so that conflicts are resolved during the cycle and not on release day.
   - **Test it.** The RC runs of the HA and Helm jobs use `HELM_CHART_BRANCH=release-pmm-X.Y.Z` with the RC images, so RC testing covers the chart that will ship.
   - **Release it.** The coordinator's "Helm PR" in step 4 becomes a commit on the release branch that sets the image tag and `appVersion` to X.Y.Z. The same commit bumps each chart's `version` from its version on `main` at that moment: minor for a PMM minor release, patch for a PMM patch release. The coordinator then opens the PR `release-pmm-X.Y.Z` → `main`. It is merged with a merge commit, as #859 and #927 were, so that each change keeps its own commit on `main`. The timing is unchanged: the PR is merged after the GA tag, once the docs are live.
   - **Delete** the branch after the merge.
   - A release with no chart changes carries only the version bump, the same PR as today.
4. **Several release branches can be open at once**, for example `release-pmm-3.10.1` for a patch and `release-pmm-3.11.0` for the next minor. Each one starts from `main`. Once one of them merges, the others merge `main` in. A change goes to the earliest release that needs it, and later releases get it through `main`. See the example below.
5. **Coordinator checks before release** (steps 3–4):
   - List open PRs that touch `charts/pmm*`, and ask about any that target `release-pmm-X.Y.Z` but are still open.
   - Flag PRs merged into the release branch whose Jira ticket has a different fixVersion.
   - Check that `main` has been merged into the release branch.

### Changes this needs

| Where | Change | Owner |
|---|---|---|
| percona-helm-charts `test-chart-lint.yaml` | Pass `--check-version-increment=false` when `GITHUB_BASE_REF` matches `release-pmm-*`. Otherwise every PR to a release branch would need a bump relative to that branch. | Shared workflow: agree it with the operator teams |
| percona-helm-charts branch protection | Add a rule for `release-pmm-*` that requires a PR and a review from `@percona/pmm-review-be` | Repository admin |
| Release coordinator (PMM-15832) | Create the branch, merge `main` into it, make the release commit and PR, delete the branch, run the checks in rule 5 | PMM |
| RC test runs | Pass the release branch as `HELM_CHART_BRANCH` | PMM QA |

No other workflow changes. The PR workflows that cover `charts/pmm*` (`test-chart-lint`, `test-chart-install`, `pmm-ha-pr-checks`) have no base-branch filter, so they also run on PRs to release branches. **[V]**

## Example: ArgoCD support during the 3.11.0 cycle

- **Ship now:** PR to `main` that bumps `pmm` from 1.10.0 to 1.10.1, with `appVersion` staying at 3.10.0. Merging it publishes 1.10.1. Later, `main` is merged into `release-pmm-3.11.0`, and the 3.11.0 release publishes 1.11.0 with ArgoCD support included.
- **Ship with 3.11.0:** the same PR, with base `release-pmm-3.11.0` and no bump. Nothing is published until the 3.11.0 release PR merges and publishes 1.11.0.

## Example: a patch and a minor in flight

PMM 3.10.0 is out, with `pmm` chart 1.10.0. Work on 3.11.0 has started, and a 3.10.1 patch is planned. Both branches start from `main`.

```
main ───●──────────●───────────●──────────────────────●──▶
      1.10.0     1.10.1      1.10.2                 1.11.0
        │       (ArgoCD)       ▲   │                    ▲
        │                      │   │ merge main         │
        ├─ release-pmm-3.10.1 ─┘   │                    │
        │   fix, release commit    ▼                    │
        └─ release-pmm-3.11.0 ─────●── release commit ──┘
            feat, feat
```

1. **Both open.** `release-pmm-3.10.1` takes the chart fixes that ship with the patch. `release-pmm-3.11.0` takes the 3.11.0 work. Chart-only changes such as ArgoCD go straight to `main`. Neither release branch changes `version`, so no two of them claim the same chart version.
2. **3.10.1 releases.** The release commit sets `appVersion` 3.10.1 and bumps the patch version from what `main` has then (1.10.1 → 1.10.2). The branch merges into `main`, which publishes 1.10.2, and is deleted.
3. **The coordinator merges `main` into `release-pmm-3.11.0`.** The 3.10.1 fixes and ArgoCD now reach 3.11.0. `Chart.yaml` and the image tag merge cleanly, because the 3.11.0 branch has not touched them. A conflict can only come from two changes to the same template, and it is resolved here, by the author of the 3.11.0 change.
4. **3.11.0 releases.** The release commit bumps the minor version from `main` (1.10.2 → 1.11.0) and sets `appVersion` 3.11.0.

Cases this does not cover on its own:

- **A fix both releases need.** It goes to `release-pmm-3.10.1` only. If 3.11.0 RC testing needs it before 3.10.1 ships, merge `release-pmm-3.10.1` into `release-pmm-3.11.0`. This is safe, because the patch ships first and its content is a subset of what 3.11.0 ships. Never merge the other way, and never cherry-pick: the same fix would then be two commits that conflict later.
- **The patch is dropped or overtaken** (3.11.0 is about to ship first). Merge `release-pmm-3.10.1` into `release-pmm-3.11.0` and delete the patch branch. Its fixes ship with 3.11.0.
- **A patch for an older minor** after the next minor has shipped, for example 3.10.2 after 3.11.0. This is not supported: `main` has moved on, and the published chart line is 1.11.x. Such a branch would have to start from the 3.10.1 release commit and publish from outside `main`. That would need its own decision.

## Consequences

- Each chart change gets an explicit "now or with X.Y.Z" choice, which shows as its base branch and can be changed until the PR merges.
- `main` always equals the published charts.
- RC testing runs on the exact chart that will ship.
- Merging `main` into open release branches is a recurring task, given to the coordinator. Conflicts surface during the cycle, not on release day.
- One change to a workflow shared with the operator teams, which they have to agree to.
- Chart patch numbers no longer follow PMM patch numbers (1.10.0, then 1.10.1 for ArgoCD, then 1.11.0 with PMM 3.11.0). `pmm-ha` already does not follow them.
- Review moves earlier. A PR to a release branch is reviewed as ready to ship, and the release PR to `main` only needs its version bump reviewed.
