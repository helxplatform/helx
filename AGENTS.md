# Agent guidance for helx

## Repository layout

- This is a monorepo. Application and Helm sources live under `services/`; do not
  restructure service directories without asking for approval.
- Buildable image services are:
  - `services/appstore` (`appstore` image)
  - `services/appstore-prepuller/controller` (`appstore-prepuller` image)
  - `services/appstore-sockets` (`appstore-sockets/server` and `appstore-sockets/monitoring` images)
  - `services/ui` (`helx-ui` image, but we call it `ui` everywhere else in this repo)
  - `services/user-mutator` (`user-mutator` image)
- Other service directories are chart-only or utility/source-only. Helm charts
  may be at the service root or under `services/<service>/chart/`.
- The umbrella chart is `deploy/helm/helx-chart`.

## CI and image publishing

- There are three workflows and no per-service workflows:
  - `.github/workflows/ci.yml` runs on pull requests and `workflow_dispatch`.
    It only validates: charts are linted and packaged to `$RUNNER_TEMP`, images
    build with `push: false`, and nothing leaves the runner.
  - `.github/workflows/develop.yml` runs on pushes to `develop`. It validates
    the same charts, publishes every image as `develop-<short-sha>`, then
    publishes the candidate umbrella (see "Candidate channels").
  - `.github/workflows/publish.yml` runs on pushes to `main`. It publishes
    charts, publishes images as `v<appVersion>`, and creates the Git tag plus
    GitHub Release when the umbrella `version:` increases.
- Shared image build logic is in `.github/actions/build-service/action.yml` and
  shared chart logic is in `.github/actions/publish-charts/action.yml`. Keep
  workflows thin and reuse these actions.
- Pull requests build only the images whose sources changed; chart edits never
  select an image. The exception is `REBUILD_ALL_IMAGE_PATHS` in
  `.github/scripts/ci.py` (`build-service`, `images.yaml`, `ci.py`, `ci.yml`):
  touching any of them builds every image. That is intentional, so a CI change
  rebuilding everything is not a bug.
- Image tags come from chart metadata, not from Git tags or commit messages:
  released images are `v<appVersion>` of the owning chart, and candidate images
  are `<channel>-<short-sha>`. There is no automatic version bumping; bump
  `appVersion` in the owning chart instead.
- Images and BuildKit cache layers are pushed only to
  `containers.renci.org/helxplatform/<image>`. Required image secrets are
  `CONTAINERHUB_USERNAME` and `CONTAINERHUB_PASSWORD`; Docker Hub is not pushed to.
  However, even though the prefix of these variables is `CONTAINERHUB_`, the actual
  name of the registry is Harbor. Please use that name when referring to the registry
  itself.
- That applies to the workflows. The local image targets in the Makefile take
  `IMAGE_REGISTRY=<base url>` to build, push, and pin against a different
  registry; it defaults to the `registry` in `.github/ci/images.yaml`, which is
  Harbor. The override reaches `ci.py` as `image-plan --registry` and
  `candidate-values --registry`, and the latter rewrites each image's
  `repository` alongside its tag, so the packaged chart names the registry the
  images were actually pushed to.
- The one exception in CI is ACR, for the Azure AI Sandbox cluster, which cannot
  pull from Harbor. When the repository variable `ACR_LOGIN_SERVER` is set,
  `develop.yml` and `publish.yml` each run `mirror-images-acr`, which copies
  every image they published from Harbor to `<ACR_LOGIN_SERVER>/helxplatform/`
  with `.github/actions/mirror-image` (no rebuild, same digest), using the
  secrets `ACR_USERNAME` and `ACR_PASSWORD`. Unset the variable and it skips.
  Only images go to ACR; charts are published to GHCR only. The chart keeps
  pinning Harbor repositories, and `deploy/helm/values/azure/defaults/values.yaml`
  repoints every built image's `repository` at ACR, so a new image in
  `.github/ci/images.yaml` needs a line there too.

## Candidate channels

A "candidate" is a single packaged umbrella chart published to a channel tag. 
(e.g. `oci://ghcr.io/helxplatform/helm-charts/helx:4.6.0-develop`)

- A candidate channel publishes one mutable prerelease umbrella chart that
  tracks a branch. `develop` publishes `<umbrella version>-develop` to
  `oci://ghcr.io/helxplatform/helm-charts/helx` and overwrites it on every push.
- Candidates are SemVer prereleases, so they always sort below the matching
  release and can never be mistaken for it.
- Candidate mode is driven by `CHART_CHANNEL` and `CHART_CHANNEL_COMMIT` in
  `.github/scripts/helm-build-chart.sh`, and only applies to the umbrella. In
  this mode local service charts are vendored by name regardless of the version
  pinned in `Chart.lock`, so the archive describes the branch tree rather than
  what is already published.
- Candidate image tags are written into the umbrella's `values.yaml` before
  packaging and restored afterwards, because `helm package` cannot take value
  overrides. Add `tag_path` to a service in `.github/ci/images.yaml` when its
  chart does not read `image.tag`. `repository_path` is its sibling, defaults
  to the `repository` key in the same block, and is only written when a
  registry override is in play. `validate-config` requires both keys to exist
  in the owning chart's `values.yaml`, since a pin that lands nowhere is
  invisible.
- The immutability preflight is skipped for candidates and must stay that way;
  it exists to protect released versions only.
- A candidate can also be numbered: `CHART_CHANNEL_BUILD` (the action's
  `channel-build`, `candidate-version --build`) makes it
  `<version>-<channel>.<build>`, published once and never overwritten. Argo CD
  caches a chart by its version string and never notices an overwritten tag,
  so anything Argo CD follows must be numbered; it follows the newest with the
  range `>=0.0.0-0`. The build must only grow (CI uses `github.run_number`),
  since SemVer compares numeric identifiers numerically. `develop.yml`
  publishes both: the mutable `<version>-develop` (`publish-candidate`), then
  the same content as `<version>-develop.<run number>`
  (`publish-numbered-candidate`), which waits for `mirror-images-acr` so a
  cluster pulling from ACR never sees a chart before its images.

## Argo CD

- Argo CD config lives in `deploy/argocd/`. `root.yaml` is applied by hand once
  per cluster and syncs `bootstrap/` (the `helx` AppProject, External Secrets,
  the `vault` ClusterSecretStore, its token-renewal CronJob, and the
  ApplicationSet). The ApplicationSet makes one Application,
  `helx-<env>`, per `envs/<env>/config.yaml`, rendering the whole umbrella with
  the cluster and env files from `deploy/helm/values/` plus
  `envs/<env>/values.yaml`, and applying `envs/<env>/manifests/`.
  `docs/argocd-setup-in-new-cluster.md` is the procedure, including taking over
  an existing Helm release.
- Argo CD renders with `helm template`: `lookup` returns nothing and
  `.Release.IsUpgrade` is always false. A chart value that generates something
  (`randAlphaNum`, `genCA`) or carries it over from the live cluster renders
  differently on every sync. `envs/<env>/values.yaml` exists to replace those
  with Vault-backed ExternalSecrets or fixed values. After changing a chart or
  those values, render twice with every values file the Application uses and
  check the two outputs are identical.
- Every ExternalSecret Argo CD renders reads Vault through the ClusterSecretStore
  `vault` (`bootstrap/vault-cluster-secret-store.yaml`), so it must set
  `secretStoreRef.kind: ClusterSecretStore`; the charts default to a
  namespaced `SecretStore`, which doesn't exist. The store logs in with one
  Vault token per cluster, held in the hand-made Secret `vault-token` in the
  `external-secrets` namespace and never committed. Its `conditions` list the
  namespaces allowed to use it, so a new environment's namespace goes there
  too.
- `deploy/helm/vault-secrets.yaml` maps each Secret those ExternalSecrets fill
  to its service and to where each key lives in the Helm values. The
  `helm-secrets-to-vault`, `vault-secrets-to-helm`, and
  `vault-secrets-from-cluster` targets (`.github/scripts/vault_secrets.py`)
  convert with it between a `secrets.yaml` for `make helm-deploy` and one JSON
  file per Secret for Vault, and `vault-secrets-upload` writes those files to
  Vault (after listing them and asking). A chart that gains such a Secret, or
  a key that isn't under a `values` block, needs an entry there too. Only the
  upload target touches Vault, none touch Git, and their output is plaintext
  secrets under the ignored `dist/`. Never run the upload target from an
  agent; test it with a fake `vault` on `PATH`, as its unit tests do.
- Migration switches (`*.migration.enabled`) need a real `helm upgrade` and
  must stay off in anything Argo CD renders. Run migrations with
  `make helm-deploy` before handing a namespace to Argo CD.

## Helm charts

- Chart build, lint, package, and publication all go through
  `.github/actions/publish-charts/action.yml`, which calls
  `.github/scripts/helm-build-chart.sh`. Published charts go to
  `oci://ghcr.io/helxplatform/helm-charts/`.
- Chart versions are immutable in OCI registries. Bump `version:` in
  `Chart.yaml` for chart changes that have already been published.
- A dependency that also exists in this tree must be pinned to exactly the
  in-tree chart's version. `validate-config` enforces this. Without it the
  version comparison in `helm-build-chart.sh` silently decides whether a chart
  is vendored from the tree or pulled from the registry, so bumping a service
  chart without bumping the umbrella pin would drop it from the umbrella with no
  warning. Bumping a service chart and the umbrella pin is one change.
- Every dependency is pinned to an exact version, so `Chart.lock` is derivable
  from `Chart.yaml` with no registry access. Regenerate it with
  `make sync-locks`, `make sync-helx-lock`, or
  `python .github/scripts/ci.py sync-lock <chart-dir>` rather than
  `helm dependency update`; `--check` verifies without writing. The digest
  reproduces Helm's `resolver.HashReq` and is covered by a test using a
  helm-generated lock as the oracle.
- `check-versions` runs on every pull request, not just those targeting the
  default branch, and on direct pushes to `develop`.
- A version bump is only required when a changed file can affect the artifact.
  Charts consult their own `.helmignore`, images consult `excludes` in
  `.github/ci/images.yaml` plus the build context's `.dockerignore`. So editing
  a chart's `.gitignore` never gates, while editing `Chart.lock` does.
- Every chart must commit a `.helmignore` with the baseline patterns in
  `REQUIRED_HELMIGNORE`, and it must not exclude `Chart.yaml`, `values.yaml`, or
  `templates/`. `validate-config` enforces both, and also rejects `.dockerignore`
  negation or `**`, which the gate cannot reason about.
- On pull requests that do not target the default branch, and on direct pushes to
  `develop`, versions are judged with `--above-release` (old name
  `--umbrella-above-release` still works): each must sit strictly above what is
  released rather than increase on every change, and may not regress against the
  base (equal is fine). "Released" is the last `v*` tag for the umbrella, and the
  `version`/`appVersion` in `origin/main`'s `Chart.yaml` for service charts and
  their images (`--release-ref`; a chart absent there has no floor, a missing ref
  is an error, no registry is queried). Equal to the release is allowed only when
  the packaged files are identical to it (main's tree, or the tag's for the
  umbrella), so merging a hotfix back needs no extra bump. The umbrella's
  dependency pins are still enforced. So only the first pull request after a
  release picks each next version. Raising the umbrella starts publishing a new
  `<version>-develop` channel automatically, since the candidate tag derives
  from it. Never pass that flag on the default branch.
- `check-versions` compares committed revisions, so an uncommitted or untracked
  chart file is invisible to it.
- Prefer fixing the ignore file over adding a CI exception. If a file never
  reaches an image, add it to that service's `.dockerignore`.
- `ambassador`, `pod-reaper`, and `resty` were vendored from subdirectories of
  helxplatform/helx-chart (`charts/<name>`), not from a repo root, so they are
  **not** subtrees: they have no merge base, they are absent from
  `SUBTREE_MAP`, and the `pull-<name>` subtree targets do not touch them. They
  have their own targets, below. `resty` in particular is deliberately ahead of
  upstream (helx-common secrets contract, caller-managed TLS, Harbor image), so
  it must never be overwritten wholesale from upstream.
- Each of those charts records the upstream commit it has incorporated in
  `services/<name>/UPSTREAM_COMMIT`. `make check-vendored-sync` reports how far
  behind each one is and lists what to run for each; it succeeds even when a
  chart is behind, since being behind an archived upstream is not a build
  failure. `STRICT=1` makes it exit non-zero instead, which is how CI gates on
  it (`check-subtree-sync` gates unconditionally; this one does not) and `make pull-vendored-chart NAME=<name>` replays only
  the commits since that record onto `services/<name>/chart`, then restamps the
  file. `pull-vendored` does all three. They are the vendored counterparts of
  `check-subtree-sync` and `pull-<name>`, and they never touch the repo root.
- A replay is a three-way apply, so it preserves local divergence and leaves a
  genuine clash as conflict markers instead of discarding it. On conflict the
  record keeps its old `upstream:` and gains a `pending:` line naming the commit
  being replayed, so the chart still reads as un-synced and nobody has to
  remember a sha. `check-vendored-sync` reports it as `REPLAY UNFINISHED`.
  Resolve the markers, then `make update-vendored-chart-stamp NAME=<name>`. That
  target is bookkeeping only: it rewrites `upstream:` in the record and edits no
  chart file, because the replay already happened in full during the pull. It
  refuses while the chart still has unmerged entries or markers. `COMMIT=<sha>`
  is only for stamping by hand.
- `git apply -3` skips hunks already present and stages what it applies, so a
  clean run is not proof anything changed. Review `git diff --cached` before
  committing, and trust `check-vendored-sync` (which compares trees) over the
  apply's exit status when deciding whether a chart is really in sync.
- `helx-chart` dependencies use the GHCR OCI registry, not the old GitHub Pages
  repository. OCI consumers need GHCR registry authentication.
- Chart-only changes should not trigger an image build; image workflows exclude
  nested `chart/` paths.

## Validation and safety

- Every container a chart renders, init containers and test pods included, must
  set `securityContext.allowPrivilegeEscalation: false`. AKS denies pods that
  leave it unset, and the umbrella build enforces it by rendering the chart
  defaults and each `deploy/helm/values/azure/envs/*` environment
  (`ci.py check-privilege-escalation`). Charts expose it as `securityContext`
  where that key already reached the containers, and as
  `containerSecurityContext` elsewhere; in appstore-sockets, `securityContext`
  is still not applied to any container. Tycho's pod template sets it itself.
- Lint values live in `.github/helm/lint-values/<chart name>.yaml`, one file
  per chart, used when that chart is linted alone. The umbrella has none to
  maintain: `ci.py lint-values` nests each dependency's file under its name (a
  `helx.yaml`, if ever added, goes on top), and both `helm lint` in
  `helm-build-chart.sh` and the render checks use that. A chart-managed Secret
  that requires values belongs in `existingSecret` mode there, or lint prints
  `[INFO] Fail:` lines. `validate-config` rejects a file not named after a chart.
- Use `helm lint` on the affected chart, then the complete chart set when
  practical. Dependency archives are not checked in. CI does not run
  `helm dependency update`; `prepare_dependencies` in
  `.github/scripts/helm-build-chart.sh` vendors each locked dependency itself,
  preferring an in-tree chart and pulling from the registry otherwise.
- Validate workflow/action YAML and inspect project diagnostics after edits.
- Preserve unrelated user changes, including untracked files and directories;
  do not commit or create branches unless requested.

## Other rules

- Do not revert changes that you notice happen that you don't expect. They are very
  likely intentional changes made by the user. If you think it relevant, you may
  ask the user whether they made the changes or if they were unintentional.
