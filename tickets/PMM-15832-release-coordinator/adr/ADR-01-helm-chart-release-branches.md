# ADR-01: Helm chart changes for a PMM release go to a `release-pmm-X.Y.Z` branch

- Status: Proposed
- Date: 2026-11-11
- Tickets: PMM-15832
- Implemented: not yet. Needs the coordinator steps below and a change to the version check in two percona/percona-helm-charts PR workflows.

## Context

The `pmm`, `pmm-ha` and `pmm-ha-dependencies` charts live in percona/percona-helm-charts, a repository PMM shares with the operator teams. CODEOWNERS gives `charts/pmm/` and `charts/pmm-ha/` to `@percona/pmm-review-be`, and everything else to the operator teams. **[V]**

**Merging to `main` is releasing.** `release.yaml` runs on every push to `main` and nowhere else. **[V]** It runs chart-releaser-action v1.6.0, which packages every chart that changed since the repository's latest release tag, then uploads a GitHub Release and updates the `gh-pages` index for each package whose version has no release yet. `skip_existing: true` skips only that upload. The next step `helm push`es every package to `oci://ghcr.io/percona/percona-helm-charts`, including those skipped. **[V]** from `cr.sh` and `release.yaml`. So a change merged without a bump probably overwrites the existing OCI tag with new content while `gh-pages` keeps serving the old package. **[I]**: GHCR and the job logs need authentication to confirm.

**PRs to `main` must bump.** Two PR workflows run `ct lint` with the version-increment check (chart-testing's default, on by explicit flag for `pmm-ha`):

- `test-chart-lint.yaml` (shared with the operator teams) lints `charts/pmm` with `--target-branch "$GITHUB_BASE_REF"`. **[V]**
- `pmm-ha-pr-checks.yaml` (PMM's) lints `charts/pmm-ha` and `charts/pmm-ha-dependencies` with `--check-version-increment=true` and no `--target-branch`, so it compares against `main` from `.github/ct.yaml`, whatever the PR's base. **[V]** That lint runs inside the `lint-test` job, before the kind cluster, the `ct install` of both charts and the render checks. None of those have `if: always()`, so a lint failure skips the HA install tests. **[V]**

Neither check is required for merging: #916, #848 and #929 changed `charts/pmm-ha` on `main` without a bump. **[V]** from git history. #916 merged after `pmm-ha` 1.6.0 was released (#909) and before #930 bumped it to 1.6.1, so users got it only with 1.6.1. **[V]** from git history.

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
4. **Merge to `main` without a version bump, and publish later by bumping.** Rejected: the next unrelated bump would ship everything that had piled up, which is the opposite of choosing. It has already happened: #916 merged to `main` unbumped and reached users only with the next bump. Meanwhile the GHCR copy of the same version probably changed under users while `gh-pages` did not (see Context).
5. **One branch per PMM release, `release-pmm-X.Y.Z`, with `main` kept as what is published.**

## Decision

Option 5. These rules apply to `charts/pmm`, `charts/pmm-ha` and `charts/pmm-ha-dependencies`.

1. **The PR's base branch is the release decision.**
   - Base `main`: the change ships when the PR merges. Use it for chart-only changes that work with the released PMM. Bump the chart's patch `version` (the repository's CONTRIBUTING rule), and leave `appVersion` unchanged.
   - Base `release-pmm-X.Y.Z`: the change ships with PMM X.Y.Z. These PRs change neither `version` nor `appVersion`; the release commit sets both once (rule 4).
   - To change the decision, retarget the PR ("Edit" next to the base branch). For that to stay a one-click change, start feature branches from `main`. Start from the release branch only when the change builds on something that is already there.
2. **Merge to a release branch only what is ready to ship.** A change that is not ready stays an open PR. If a merged change must not ship after all, revert it on the release branch, and re-land it on the next release branch by reverting the revert.
3. **Lifecycle of `release-pmm-X.Y.Z`:**
   - **Create** it from `main`. The coordinator creates `release-pmm-<next>` when it closes the previous release (step 6, where it already moves leftover tickets to the next Jira version). Anyone may create it earlier, named after the Jira fixVersion.
   - **Keep it current** by merging `main` into it, never by rebasing, because other PRs are based on it. Do this after each merge to `main` that touches `charts/pmm*`, and at the latest before RC testing, so that conflicts are resolved during the cycle and not on release day.
   - **Test it.** The RC runs of the HA and Helm jobs use `HELM_CHART_BRANCH=release-pmm-X.Y.Z` with the RC images, so RC testing covers the chart that will ship.
   - **Release it.** The coordinator's "Helm PR" in step 4 becomes a commit on the release branch that sets the image tag and `appVersion` to X.Y.Z. The same commit bumps the `version` of `pmm`, `pmm-ha` and every other chart the branch changed (in practice `pmm-ha-dependencies`) from its version on `main` at that moment: minor for a PMM minor release, patch for a PMM patch release. A changed chart left unbumped would get no GitHub Release, probably overwrite its GHCR tag, and fail `pmm-ha-pr-checks` on the release PR. The coordinator then opens the PR `release-pmm-X.Y.Z` → `main`. It is merged with a merge commit, as #859 and #927 were, so that each change keeps its own commit on `main`. The timing is unchanged: the PR is merged after the GA tag, once the docs are live.
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
| percona-helm-charts `pmm-ha-pr-checks.yaml` | In the `ct lint` call, add `--target-branch "$GITHUB_BASE_REF"` and replace `--check-version-increment=true` with `--check-version-increment=${{ github.base_ref == 'main' }}`. **Prerequisite:** otherwise every `pmm-ha` PR to a release branch fails the lint against `main`'s version and skips the HA install tests. | PMM |
| percona-helm-charts `test-chart-lint.yaml` | Add `--check-version-increment=${{ github.base_ref == 'main' }}` (it already passes `--target-branch "$GITHUB_BASE_REF"`). Otherwise `pmm` PRs to a release branch show a failed lint, as #921 did on `PMM-HA-GA` (run 36879153059, reported in the review of pmm-specs#18). | Shared workflow: agree it with the operator teams |
| Release coordinator (PMM-15832) | Create the branch, merge `main` into it, make the release commit and PR, delete the branch, run the checks in rule 5 | PMM |
| RC test runs | Pass the release branch as `HELM_CHART_BRANCH` | PMM QA |

Nothing else changes in percona/percona-helm-charts:

- **Workflows.** The PR workflows that cover these charts (`test-chart-lint`, `test-chart-install`, `pmm-ha-pr-checks`) have no base-branch filter, so they also run on PRs to release branches. **[V]** `PMM-HA-GA` passed the `pmm-ha` check only because #968 bumped `pmm-ha` to 1.8.0 on the branch early, while `main` was on 1.6.1. **[V]** A release branch could pass the same way by bumping when it is created. But then the version would be fixed before release time, and two open branches (rule 4) could claim the same version, so this decision bumps only in the release commit.
- **Branch protection.** Not needed. Changes reach a release branch through reviewed PRs, as they reached `PMM-HA-GA`, and the branch publishes nothing: only the merge to `main` does, through `main`'s existing rules.

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
- One line changes in PMM's `pmm-ha-pr-checks.yaml`, and one in the shared `test-chart-lint.yaml`, which the operator teams have to agree to. No repository settings change.
- Chart patch numbers no longer follow PMM patch numbers (1.10.0, then 1.10.1 for ArgoCD, then 1.11.0 with PMM 3.11.0). `pmm-ha` already does not follow them.
- Review moves earlier. A PR to a release branch is reviewed as ready to ship, and the release PR to `main` only needs its version bump reviewed.
