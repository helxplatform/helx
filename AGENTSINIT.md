# Getting started in the HeLx monorepo

Read this first. It explains what HeLx does, how the pieces fit together, and
where everything lives. The rules for working here (versioning, CI, safety) are
in [`AGENTS.md`](AGENTS.md); when the two seem to disagree, `AGENTS.md` wins.

## What HeLx is

HeLx lets researchers sign in through UNC single sign-on (SAML) and launch
containerized tools, such as Jupyter, RStudio, VS Code, and browser desktops
("webtop"), on Kubernetes. Each launched app gets the user's home directory
and their LDAP identity (uid, gid, groups), so files keep the right owner
across apps.

The whole platform is deployed as one Helm chart, the umbrella `helx` in
`deploy/helm/helx-chart`. The umbrella's `version` is the HeLx release number:
the Git tag `v<version>` and the GitHub Release are created when it increases
on `main`.

## What happens when a user opens an app

1. **resty** (OpenResty, `services/resty`) is the front door. Its routes are in
   `services/resty/chart/templates/nginx-default-configmap.yaml`:
   - `/helx` and `/static/frontend` go to `ui:80`, the React front end.
   - `/ws` goes to `appstore-sockets-service:5555`, the websocket server.
   - `/` goes to `appstore:8000`. When appstore answers 404, resty retries
     the path under `/helx/`, so the front end handles its own routes.
2. **appstore** (`services/appstore`, Django) serves the login page, checks
   the user's session, and owns the API. Launching an app calls **Tycho**.
   Tycho is not a separate service: it is a Python package inside appstore,
   at `services/appstore/appstore/tycho`. It renders the Jinja templates in
   `tycho/template/` and creates a Deployment and a Service named
   `<app>-<guid>`, labelled `username`, `app-name`, `reaper-label`, and
   `tycho-guid`.
3. **The app catalog is not in this repository.** Tycho reads app definitions
   from `helxplatform/helx-apps` on GitHub, from the branch named in values
   (see Traps). On a cluster without GitHub access (ASHE), resty's
   `artifactCache` serves a copy at `/artifact/`.
4. **user-mutator** (`services/user-mutator`, a Go mutating admission webhook)
   intercepts every Deployment with a `username` label. It looks the user up
   in LDAP, sets the pod's uid and gid, adds the volumes its configuration
   lists (such as the user's home directory), and injects the `nslcd-sidecar`
   container so the user's name and groups resolve inside the app.
5. The browser then opens `/private/<app>/<user>/<guid>/...`. For each request
   resty asks appstore's `/api/v1/private-route/` whether this user owns the
   app and which Service and port it uses, then proxies to that Service through
   cluster DNS.

Around that path:

- **helx-ldap** (`services/helx-ldap`) wraps the `openldap-stack-ha` chart.
  It is the in-cluster LDAP (Service `openldap`) that user-mutator reads.
- **ldap-sync** (`services/ldap-sync`, Go) copies users and groups from
  `ldaps://ldap.unc.edu` into helx-ldap. Each entry goes through a "hook"
  sidecar (for example `unc-group-x` in `hooks/`) that rewrites it, assigning
  gids. Its `pvcGroup` plugin can create a PVC for every synced group.
- **appstore-prepuller** (`services/appstore-prepuller`, Python) runs a
  CronJob that reads the same helx-apps catalog and keeps a DaemonSet whose
  init containers pull every app image onto every node, so launches are fast.
- **appstore-sockets** (`services/appstore-sockets`) is a TypeScript websocket
  server plus a Python `monitoring/` process. It pushes pod status to the
  front end.
- **pod-reaper** (`services/pod-reaper`) deletes apps that have run longer than
  `max_duration`, matching on the `reaper-label` Tycho sets.
- **ambassador** (`services/ambassador`) is legacy. resty replaced it
  (appstore's `tycho.appRoutingMode: proxy`), and it is commented out of the
  umbrella's dependencies.

## Repository map

| Directory | What it is | Images CI builds | Where it came from |
|---|---|---|---|
| `services/appstore` | Django app with Tycho inside (Python 3.10) | `appstore` | subtree of `helxplatform/appstore` |
| `services/appstore/chart` | its chart | | separate subtree of `appstore-chart` |
| `services/ui` | React front end, served by nginx | `helx-ui` | subtree of `helxplatform/helx-ui` |
| `services/ui/chart` | its chart | | separate subtree of `ui-chart` |
| `services/appstore-sockets` | TypeScript server, Python `monitoring/` | `appstore-sockets/server`, `appstore-sockets/monitoring` | subtree |
| `services/appstore-sockets/chart` | its chart | | separate subtree of `appstore-sockets-chart` |
| `services/appstore-prepuller` | Python controller in `controller/` | `appstore-prepuller` | subtree |
| `services/user-mutator` | Go webhook in `webhook-server/` | `user-mutator`, `nslcd-sidecar` | **squash** subtree |
| `services/ldap-sync` | Go sync service, hooks in `hooks/` | `ldap-sync` (hook images are not built by CI) | subtree |
| `services/helx-ldap` | OpenLDAP chart wrapper and admin scripts | none | subtree |
| `services/resty`, `services/pod-reaper`, `services/ambassador` | charts only | none | vendored from `helxplatform/helx-chart/charts/<name>` |
| `deploy/helm/helx-common/chart` | library chart for the shared Secret pattern | none | lives here |
| `deploy/helm/helx-chart` | the umbrella chart | none | lives here |
| `deploy/helm/values/<platform>/` | values for each cluster (see Environments) | | lives here |
| `deploy/local-dev/` | `make help` formatter, local values-file list | | lives here |
| `.github/` | workflows, `scripts/ci.py`, `ci/images.yaml`, lint values | | lives here |

Subtree remotes, branches, and merge modes are the `*_URL`, `*_BRANCH`, and
`SUBTREE_MAP` lines at the top of the `Makefile`. Upstream repositories still
receive changes; `make pull-<name>` merges one in and `make help-subtrees`
lists them all. The vendored charts record their upstream commit in
`services/<name>/UPSTREAM_COMMIT` and are synced with
`make pull-vendored-chart NAME=<name>`. Never replace `resty` wholesale from
upstream: it is deliberately ahead.

The umbrella's `Chart.yaml` pins each service chart to an exact version, and
`.github/ci/images.yaml` is the authoritative list of images, which chart owns
each one, and which files count as its source.

## Where to read more

- Root [`README.md`](README.md): the developer workflow, from setup to version
  bumps and deploying a branch.
- [`.github/CI.md`](.github/CI.md): how the workflows, `ci.py`, and
  `helm-build-chart.sh` work.
- [`docs/DeploymentMigration.md`](docs/DeploymentMigration.md): upgrading an
  existing deployment across Secret and chart changes.
- [`docs/QUIRKS.md`](docs/QUIRKS.md): known deployment caveats.
- [`deploy/helm/helx-common/chart/README.md`](deploy/helm/helx-common/chart/README.md):
  the Secret contract every chart uses (`secret.mode` and friends).
- Chart READMEs. Where a `README.md.gotmpl` sits beside one, the README is
  generated by `helm-docs` from the template and the `# --` comments in
  `values.yaml`. Nothing runs helm-docs automatically: edit the template or
  the comments, then run `helm-docs` in that chart directory.
- Service READMEs came from the standalone repositories. Their descriptions of
  the code are useful; their CI, Docker Hub, and release sections may still
  describe the old per-repository setup. Trust `AGENTS.md` and `.github/CI.md`
  over them.
- `services/ldap-sync/CLAUDE.md` and `services/user-mutator/CLAUDE.md` give
  service-specific guidance and load automatically when you work in those
  directories.

## Commands

All from the repository root. Python tooling installs itself into `.venv` on
first use.

| Command | What it does | Time |
|---|---|---|
| `make ci-validate-everything` | chart metadata, locks, `.helmignore`, and `images.yaml` | under a second |
| `make ci-tests` | unit tests for `ci.py` | about 10 seconds |
| `make ci-check-versions` | the version gate (see "What a change costs") | a few seconds |
| `make check-locks` | every `Chart.lock` matches its `Chart.yaml` | under a second |
| `make pre-push` | all of the above plus `git diff --check` | under 15 seconds |
| `make build-chart SERVICE=<name>` | vendor dependencies, lint, and package one chart | a second or two |
| `make build-helx-chart` | package the umbrella into `dist/charts` | depends on network |
| `make docker-build SERVICE=<name>` | build one image as CI does | minutes |

`build-chart` for appstore, helx-ldap, and ldap-sync, and therefore
`build-helx-chart`, pull third-party charts (postgres, openldap), so they need
network access. Charts from this repository are always taken from the tree.

**CI never runs the services' own tests.** It lints and packages charts and
builds images, nothing more. Run these yourself:

| Service | Command (in the service directory) |
|---|---|
| appstore | `make test`, in a Python 3.10 environment; its pins (`pyyaml==5.4.1`, `cython<3`) do not install on recent Pythons |
| user-mutator | `make go-test` (Go 1.26) |
| ldap-sync | `go test ./...` (Go 1.23) |
| ui | `npm run lint`; there are no tests |
| appstore-sockets, appstore-prepuller | no tests |

Deploying a local build to a cluster is `build-helx-images`, then
`load-helx-images` (kind, minikube, k3d) or `push-helx-images`, then
`build-helx-chart`, then `helm-deploy`; `make help-local-dev` explains each.

## What a change costs

Every chart and image is versioned by hand. The gate (`ci-check-versions`)
fails a pull request when a file that reaches a published artifact changed but
its version did not. On pull requests into `develop`, a version only has to
sit above what is released on `main`, so once someone has bumped a service
since the last release, further changes to it need nothing more.

Whether a file "reaches" an artifact:

- For a chart: its `.helmignore` decides. Chart edits never count against an
  image.
- For an image: its `sources` and `excludes` in `.github/ci/images.yaml`, plus
  the build context's `.dockerignore`. Nothing else is consulted, so a file
  the final image never contains can still count.

Two examples, for a service whose `appVersion` equals the one on `main`:

- A typo fix in `services/appstore/README.md`. appstore's `.dockerignore` does
  not exclude `README.md`, so the image counts as changed. You must bump
  `appVersion` and `version` in `services/appstore/chart/Chart.yaml`, then the
  appstore pin in `deploy/helm/helx-chart/Chart.yaml`, then the umbrella's own
  `version` if it is not already above the last `v*` tag. Then run
  `make sync-helx-lock`.
- The same fix in `services/user-mutator/README.md` or `services/ui/README.md`
  costs nothing: both `.dockerignore` files exclude it.

Before pushing, run `make pre-push`. It compares against your local `develop`
branch, so update that first or pass `BASE=origin/develop`. For a pull request
into `main`, use
`make ci-check-versions BASE=origin/main CHECK_VERSIONS_FLAGS=--include-untracked`
instead, because `--above-release` must not be used there.

## Environments and values

Values are layered per platform, last file wins:

1. the umbrella's own `deploy/helm/helx-chart/values.yaml`
2. `deploy/helm/values/<platform>/defaults/values.yaml`
3. `deploy/helm/values/<platform>/envs/<env>/values.yaml`
4. a values file with real secrets, kept outside the repository

Keys are nested under the subchart's name (`appstore:`, `resty:`, ...), plus
`global:`. A `# CHANGEME` in a defaults file marks a value every environment
must set. `deploy/local-dev/local-values-files.env` (gitignored; copy the
`.sample`) lists the files `make helm-deploy` passes.

| Platform | Cluster | Notes |
|---|---|---|
| `azure` | AKS | An Azure Policy rejects any container without `allowPrivilegeEscalation: false`; the umbrella build checks this for every `azure/envs/*`. resty `dnsResolver: 10.0.0.10`. cert-manager cannot issue resty's TLS Secret there, so it is created separately. |
| `sterling` | RENCI on-prem Kubernetes (Kubespray); env `helx-test` | resty uses the default resolver, `kube-dns.kube-system.svc.cluster.local`. |
| `ashe` | OpenShift without GitHub access | resty `dnsResolver: 172.30.0.10`; the app catalog comes through resty's artifact cache. |

Argo CD manifests live under `deploy/argocd/` on the `argocd-setup` branch.

## Traps

Each of these has cost someone time.

- **The app-catalog branch is set in two places.**
  `appstore.tycho.externalAppRegistryBranch` and
  `appstore-prepuller.appRegistry.branch` must name the same helx-apps
  branch. If the first is empty it defaults to `v<appstore appVersion>`, so
  bumping appstore silently changes which catalog branch it loads.
- **"Brand" is three settings.** `appstore.djangoSettings` picks the settings
  module and therefore the product whose app list appstore offers (`helx`
  everywhere). `appstore-prepuller.appRegistry.brand` picks the product whose
  images get pre-pulled; when it differs from appstore's, nodes warm images
  for a different app list. `ui.config.brand_name` only picks the front end's
  branding.
- **pod-reaper's app list is hand-written.** `require_label_values` lists app
  names. A new app in helx-apps is never reaped until someone adds it there.
- **resty hard-codes neighbours.** It expects Services named `appstore`, `ui`,
  and `appstore-sockets-service` in the same namespace as the launched apps.
  A `fullnameOverride` on any of them needs the matching
  `global.*_service_name`.
- **A wrong `dnsResolver` breaks every launched app.** resty resolves each
  `/private` upstream at request time through `resty.dnsResolver`, so copying
  one platform's value to another breaks every app, and a hostname nginx cannot
  resolve stops resty, and with it the whole site, from starting.
- **ui values are pasted in with `sed`.** `services/ui/bin/populate_env`
  substitutes them, so URLs need escaped slashes (`https:\/\/...`) and
  booleans are the strings `"true"` and `"false"`. Brand images still load
  from `raw.githubusercontent.com/helxplatform/appstore` at
  `appstore_asset_branch`.
- **Tycho templates are not Helm.** Files in
  `services/appstore/appstore/tycho/template/` are Jinja, rendered when an
  app launches. Changing one is an appstore image change.
- **appstore writes migrations at startup.** Its container runs `make start`,
  which runs `makemigrations` before `migrate`. A model change without a
  committed migration still "works" by generating one inside the pod.
- **appstore's tests skip the deployed settings.** `make test` loops over the
  `BRANDS` list in `services/appstore/Makefile`, which does not include
  `helx`, the settings module every environment uses.
- **Nothing builds the ldap-sync hook images.** `services/ldap-sync/hooks/` is
  excluded from the ldap-sync image, so a hook change passes the version gate
  with no bump, and CI never builds the hook's own image (for example
  `unc-group-x`). It only reaches a cluster once someone publishes that image
  and updates its tag under `ldap-sync.config.hooks` in values.
- **Image variants share a version.** Both user-mutator images, and both
  appstore-sockets images, take their chart's single `appVersion`. Bumping it
  republishes both.
- **Chart-managed Secrets keep their old values.** With `secret.mode: values`,
  a key already in the live Secret wins over `secret.values` unless the chart
  passes `preserveKeys`, so editing a value does not rotate it. Every chart
  needs an explicit `secret.mode`; rendering fails without one.
- **`charts/` directories hold the last build.** `deploy/helm/helx-chart/charts/`
  and `services/*/chart/charts/` contain whatever was last vendored. Run
  `make build-helx-chart` before `helm template deploy/helm/helx-chart`, or you
  render stale subcharts.
- **Use `make sync-locks`, not `helm dependency update`.** Locks are generated
  from `Chart.yaml` alone. `helm dependency update` reaches out to the
  registries (GHCR needs a login) and downloads archives to get the same lock.
- **Local tools can differ from CI.** CI pins Helm 3.18.6, so with Helm 4 a
  clean local lint is good evidence but not proof. user-mutator needs Go 1.26,
  and an older Go tries to download a newer toolchain.
- **No workflow checks upstream drift.** `check-subtree-sync` and
  `check-vendored-sync` exist only for local use.

## Safety rules

`AGENTS.md` has the full list. The ones most often missed:

- Never run anything against Harbor, ACR, GHCR, or the chart index, even
  read-only. Test CI logic against synthetic fixtures.
- Investigate clusters with `get`, `describe`, and `logs` only; give the user
  any command that changes state.
- Say what a script does before running it.
- Do not commit, create branches, or revert changes you did not make unless
  asked.
