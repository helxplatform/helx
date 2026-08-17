# HeLx monorepo CI/CD

This directory contains the shared GitHub Actions implementation for validating
service images and Helm charts, publishing immutable artifacts, and recording a
compatible set of component versions as a marked monorepo release.

## Implementation map

Each executable has a short `main` flow and delegates individual policies to
named functions:

- `helm-select-charts.sh` resolves the comparison baseline and selects direct and
  reverse-dependent charts.
- `helm-build-chart.sh` prepares locked dependencies, lints, and packages one
  chart.
- `helm-preflight.sh` distinguishes a missing chart from an existing identical or
  conflicting immutable version.
- `helm_metadata.py` parses and validates the limited Helm dependency metadata
  needed by those shell scripts.
- `release_lib.py` owns release baselines, semantic deltas, release invariants,
  image build decisions, and monorepo tag selection.
- `release-plan.py` is the planning command-line entry point;
  `release-baseline.py` exposes baseline lookup to chart selection.
- `release-promote.py` validates matrix-job digest handoffs, preflights registry
  state, promotes semantic tags, and materializes the compatibility manifest.

The shell files contain command orchestration; structured metadata and release
policy live in unit-tested Python functions.

## Release flow

For `main`, publication is serialized in this order:

1. `Publish-Helm-Charts` determines chart changes relative to the last successful
   marked monorepo release (or the current push range before the first release).
2. Every selected chart and its local reverse dependents are built and linted.
3. Directly changed service charts are published or verified as already identical.
4. The umbrella chart is published only after all selected service charts succeed.
5. A successful Helm run triggers `Build-Protected-Services` for the same commit.
6. Changed images are built under immutable `staging_<full-commit-sha>` tags.
7. The release job verifies the registry staging digest against the digest returned
   by each build job, promotes semantic image tags, and verifies unchanged images.
8. Only then does CI create the marked annotated Git tag and GitHub Release.

The final Git tag therefore identifies a commit whose selected charts and images
have completed publication. Publication jobs are FIFO and are not intentionally
cancelled or replaced by newer protected-branch pushes.

`develop` follows the same Helm-success gate, then builds all configured images
under `develop_<full-commit-sha>`. It does not create semantic image tags, a Git
tag, or a GitHub Release.

## Image validation and publication

The buildable image definitions are centralized in
[`release/components.json`](release/components.json):

| Source | Registry repository |
| --- | --- |
| `services/appstore` | `containers.renci.org/helxplatform/appstore` |
| `services/appstore-prepuller/controller` | `containers.renci.org/helxplatform/appstore-prepuller` |
| `services/appstore-sockets` | `containers.renci.org/helxplatform/appstore-sockets/server` |
| `services/appstore-sockets/monitoring` | `containers.renci.org/helxplatform/appstore-sockets/monitoring` |
| `services/ui` | `containers.renci.org/helxplatform/helx-ui` |
| `services/user-mutator` | `containers.renci.org/helxplatform/user-mutator` |

Pull requests and non-protected branch pushes run credential-free Docker builds
for the affected service. These builds use a local `test_<branch>_<short-sha>` tag
only as a BuildKit label; they do **not** log in or push an image. Manual image
runs are also validation-only and cannot choose an arbitrary registry tag.

All image logic is implemented by
[`actions/build-service/action.yml`](actions/build-service/action.yml). Pushed
builds include provenance and SBOM attestations. Feature validation uses the
GitHub Actions cache; protected builds use the service's Harbor build cache.

### Image version rules

For a component with an image:

- source changes require an increase to the chart's `appVersion`;
- the semantic image tag is `v<appVersion>`;
- semantic tags are never overwritten with another digest;
- chart-only files excluded by `components.json` must also be excluded from the
  Docker build context (for example with `.dockerignore`);
- changing shared image-build/release code rebuilds all images, but does not
  create new semantic tags for components whose `appVersion` is unchanged.

Harbor should additionally enforce immutable semantic tags. Promotion is
necessarily a sequence of registry operations rather than a cross-repository
transaction, but CI preflights every promotion before creating any tag and is
idempotent when rerun with the same staged digests.

## Helm chart validation and publication

Service chart roots are discovered from `services/*/chart/Chart.yaml`; the
umbrella chart is `deploy/helm/helx-chart`. A newly added service chart therefore
does not need to be added to a hardcoded CI matrix. Manual validation accepts
`all` or a discovered chart directory.

Chart behavior by event:

| Event | Validate | Publish |
| --- | --- | --- |
| Pull request | Changed charts and local reverse dependents | Never |
| Non-protected branch push | Changed charts and local reverse dependents | Never |
| Manual dispatch | Requested chart/reverse dependents, or all | Never |
| `develop` push | Changed charts/reverse dependents | Never |
| `main` push | Changes accumulated since the last marked release | Directly changed charts |

A change to Helm CI itself validates every chart but publishes none unless chart
source also changed. Local `file://` reverse dependents are added to validation,
so a library-chart change also checks its consumers.

The reusable implementation is
[`actions/publish-charts/action.yml`](actions/publish-charts/action.yml), with
scripts under [`scripts/`](scripts/). Helm is pinned to `3.18.6`.

### Dependency and lockfile rules

- Every chart declaring dependencies must commit `Chart.lock`.
- CI uses `helm dependency build`, not `helm dependency update`, so it does not
  silently recalculate dependency versions.
- `helm lint --with-subcharts` is intentionally not used. Each repository-owned
  chart is validated directly, and enabling that flag caused unrelated duplicate
  linting/failures in parent charts.
- For umbrella validation, matching service dependencies from the checkout are
  packaged locally first. This permits validation before a newly bumped service
  version exists in GHCR while preserving the umbrella's locked versions.
- Selected service charts publish before the umbrella chart.

Chart versions in GHCR are immutable. CI first compares the local package with an
existing package of the same name/version by recursively unpacking dependency
archives. An identical package is safely reused, which makes a full retry after
partial publication possible. Different content under an existing version fails
closed; increment `version` in `Chart.yaml`.

Charts publish to:

```text
oci://ghcr.io/helxplatform/helm-charts
```

Publication uses the job-scoped `GITHUB_TOKEN`; no personal GHCR token is
required.

## Marked monorepo releases

Release planning is implemented in
[`release/release_lib.py`](release/release_lib.py) and configured by
[`release/components.json`](release/components.json).

A release baseline must be:

- an annotated `v<semver>` Git tag;
- an ancestor of the commit being released; and
- contain the exact marker line `helx-monorepo-release` plus an embedded,
  checksummed compatibility manifest.

The repository `v*` Git tag namespace is reserved exclusively for these
monorepo compatibility releases. Every `v<semver>` Git tag must be annotated and
contain the release marker and embedded manifest; an unmarked or lightweight
`v*` tag is a policy violation that stops release planning. Individual service
versions belong in chart metadata, OCI chart versions, and container-image tags,
not repository Git tags. Historical tags in the separate service repositories
are unaffected.

The first marked monorepo release is configured as `v4.5.7`, continuing the
existing umbrella `4.5.6` lineage. Before that first release only, existing
semantic image tags are adopted at their current digest and missing tags are
filled from the staged build. If `v4.5.7` becomes occupied before bootstrap,
change `initial_version` rather than deleting or overwriting the tag.

After bootstrap, the monorepo version bump is the highest semantic delta among
all component chart versions and application versions since the previous marked
release:

- any major component delta -> monorepo major;
- otherwise, any minor delta -> monorepo minor;
- otherwise -> monorepo patch;
- component or image removal -> monorepo major;
- documentation/CI-only changes with no component delta -> monorepo patch.

For example, if `user-mutator` changes from `1.7.2` to `1.7.3` and all other
component versions remain unchanged, `v4.1.6` advances to `v4.1.7`.

Each GitHub Release attaches `helx-release-manifest.json`, which records every
component's chart version, `appVersion`, component version, semantic image ref,
and immutable image digest ref. The same manifest is embedded in the annotated
Git tag.

## Required repository configuration

### GitHub environments and Harbor secrets

Create these GitHub environments:

- `harbor-staging`
- `harbor-production`

Define both secrets in each environment:

```text
CONTAINERHUB_USERNAME
CONTAINERHUB_PASSWORD
```

Use different Harbor service accounts and repository/tag permissions where
possible:

- `harbor-staging`: push `develop_*` and build-cache tags only;
- `harbor-production`: push `staging_*`, semantic `v*`, and production build
  caches.

Only trusted protected branches trigger workflows that can access these
environments. Optional required reviewers can be configured on
`harbor-production`; note that matrix staging builds will each reference that
environment.

The repository Actions policy must allow the workflow's explicit permissions:

- `packages: write` for GHCR chart publication;
- `contents: write` for the final annotated tag and GitHub Release.

### Branch and tag protection

Use GitHub rulesets for `main` and `develop`:

1. require pull requests;
2. require the relevant chart/image validation checks;
3. require branches to be current before merge;
4. restrict force pushes and deletions;
5. restrict bypasses;
6. reserve `v*` tags for GitHub Actions and permit it to create marked releases.

GitHub does not provide a standalone “lock this directory” switch. Protect CI
source with `CODEOWNERS` plus a rule requiring CODEOWNER approval. Once the real
owner is known, add an entry such as:

```text
/.github/ @your-org/ci-maintainers
```

Do not use that placeholder literally. GitHub Enterprise rulesets can add more
restrictive path-based policies, but `CODEOWNERS` plus protected-branch review is
the portable baseline.

The workflow files must be present on the default branch. In particular,
`workflow_run` only triggers `Build-Protected-Services` from workflow definitions
known to the default branch, which is why merging the CI-only PR before resuming
the secrets PR is the safe rollout order.

## CI-only branch contents

A separate CI PR is the recommended rollout. Include:

- `.github/**`;
- `services/appstore/chart/.gitignore` and the committed
  `services/appstore/chart/Chart.lock`;
- quoted `services/nfs-server/chart/Chart.yaml` `appVersion` metadata;
- the UI chart/image repository alignment changes;
- the appstore-prepuller chart/default image-tag alignment changes;
- `chart/` exclusions in `services/appstore/.dockerignore` and
  `services/appstore-sockets/.dockerignore`.

Do **not** include the current `secrets-options` umbrella dependency changes that
refer to unpublished `appstore:6.0.0` and `appstore-sockets:3.0.0`, or the LDAP and
Argo CD work, in that CI-only PR. Start the CI branch from the current default
branch and apply only the files above. After it merges, rebase or merge that
change back into `secrets-options`.

## Adding or changing a component

When adding a buildable image or release-manifest component:

1. add/update its chart metadata and committed lockfile;
2. add the component/image definition to `release/components.json`;
3. add a credential-free image validation workflow if it builds an image;
4. ensure chart-only files are outside or ignored by the Docker context;
5. update this README's image table;
6. run the release unit tests and chart selector simulations.

Adding a chart-only `services/<name>/chart` is automatically discovered for Helm
validation/publication, but it still needs a `components.json` entry if it must
appear in the compatibility manifest.

## Local validation

Useful focused checks are:

```bash
bash -n .github/scripts/helm-*.sh
python3 -m unittest discover -s .github/release -p 'test_*.py'
python3 -m unittest discover -s .github/scripts -p 'test_*.py'
python3 .github/scripts/release-plan.py --mode release --output /tmp/release-plan.json
git diff --check
```

Run `actionlint` when available. The installed version must understand GitHub's
`concurrency.queue: max`; older `actionlint` releases may report that supported
field as unknown.

Service-specific ESLint, UI, Django, and other language-level test coverage is
intentionally outside this rollout and should be added in a subsequent change.
