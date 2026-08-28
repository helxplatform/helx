## HeLxPlatform
This is the HeLxplatform monorepo. From July 2026 and onward all changes to the code should flow through here. In effort to make HeLx simple to maintain, deploy and automate the platform has been united into a Majestic Monorepo!
## DevEx

Everything CI does can be run locally with the same scripts CI uses, so you can
get a green answer before pushing. The CI internals are documented separately in
[`.github/README.md`](.github/README.md); this section is the working developer's
view.

### Prerequisites

You need `git`, `helm` 3.x, and Python 3 on your PATH. CI pins Helm 3.18.6 and
Python 3.12; anything close works locally. Docker is only needed to build images.

Python tooling lives in a project virtualenv:

```bash
make ci-pip-install     # creates .venv and installs PyYAML, the only dependency
```

Every Python target provisions `.venv` automatically the first time, so you can
skip that step and just run what you need. Provisioning happens once and is
re-run only when `.github/requirements-ci.txt` changes.

Do not `pip install` into your system Python — most modern installs are
externally managed (PEP 668) and will refuse. To use your own interpreter
instead, set `PYTHON`, which also disables the virtualenv entirely:

```bash
make PYTHON=/path/to/python ci-tests
```

You never need to activate the virtualenv. `make` targets and the scripts in
`.github/scripts/` invoke `.venv/bin/python` by path, which finds its own
packages whether or not it is activated. Activation is only a convenience if you
want to call `python` yourself:

```bash
source .venv/bin/activate
```

### First-time clone

```bash
make setup            # add every subtree remote and any missing service subtree
make install-hooks    # run the pre-push checks automatically (optional)
```

`make help` lists the setup targets and indexes the rest by topic:
`make help-subtrees`, `make help-ci`, `make help-locks`, and
`make help-all-vars` for every variable the targets accept.

Those topics are generated from the Makefile itself by
[deploy/local-dev/make-help.awk](deploy/local-dev/make-help.awk), so adding a
target means documenting it in one place. Put a comment block directly above
it, separated by a blank line from whatever came before, whose first line names
the target:

```make
##@ ci Building and inspecting one service

# docker-build SERVICE=<name>: Build one service image as CI builds it
# Further comment lines continue the description.
docker-build:
```

A block that does not open with `<target>:` is a note to whoever reads the
Makefile and stays out of the help. `##@ <topic> <title>` opens a section, and
`##>` emits a line verbatim; sections are buffered by title, so a target lands
in the right group no matter where it sits in the file. Comments cannot expand
`$(VARIABLES)`, so spell out anything a reader needs to see.

### Commands you will use often

| Command | What it does |
| --- | --- |
| `make pre-push` | Every check CI will run that can run locally |
| `make ci-validate-everything` | Validate every chart, lock, `.helmignore`, image definition, and Dockerfile |
| `make ci-check-versions` | Run the version gate the way CI will |
| `make ci-tests` | Run the CI suite's own unit tests |
| `make sync-locks` | Regenerate every `Chart.lock` from its `Chart.yaml` |
| `make sync-helx-lock` | Same, umbrella chart only |
| `make check-locks` | Verify every lock without writing |
| `make ci-build-chart SERVICE=<name>` | Vendor dependencies, lint, and package one service chart |
| `make ci-build-helx-chart` | Package the umbrella chart |
| `make ci-helm-deploy` | Install or upgrade a release from that package |
| `make ci-uninstall-release RELEASE=<name>` | Uninstall a release and delete the storage and credentials it leaves behind |
| `make docker-build SERVICE=<name>` | Build one service image as CI builds it |
| `make ci-locked-deps SERVICE=<name>` | Print that chart's resolved dependency tuples |
| `make ci-candidate-version` | Print the version the candidate channel publishes under |
| `make help` | Setup targets, plus an index of the help topics below |
| `make help-subtrees` | Subtree pulls and vendored chart mirrors |
| `make help-ci` | Checks, chart and image builds, and local deploys |
| `make help-locks` | Chart.lock maintenance |
| `make help-all-vars` | Every variable the targets accept |

### Working on a chart

Edit the chart, then:

```bash
make ci-build-chart SERVICE=<name>
```

That runs exactly what CI runs: it vendors each locked dependency (preferring an
in-tree chart over the registry), runs `helm lint`, and packages the chart. It
prints the resulting `.tgz`, which you can install directly:

```bash
helm upgrade --install <release-name> /path/to/<name>-<version>.tgz -n <namespace>
```

Three rules the version gate will hold you to, so it's cheaper to do them up
front:

1. **Bump `version:` in `Chart.yaml`** if you changed anything in the service at all.
   Editing `.gitignore` does not count; editing `templates/`, `values.yaml`,
   `Chart.yaml`, `Chart.lock`, or `.helmignore` does. The chart's own
   `.helmignore` is the authority.
2. **If the chart is an umbrella dependency, bump its pin too.** The declared
   version in `deploy/helm/helx-chart/Chart.yaml` must equal the in-tree version.
   Without this the umbrella silently keeps shipping the previous version.
3. **Run `make sync-locks`** if you touched any `dependencies:` block, and commit
   the lock alongside the chart.

### Adding or changing a dependency

Edit `dependencies:` in `Chart.yaml`, then:

```bash
make sync-locks
```

Do **not** use `helm dependency update`. Every dependency here is pinned to an
exact version, so the lock needs no resolution and `sync-locks` derives it with
no network and no registry login. That also means it works for a version that is
not published yet. A bumped service chart is not in GHCR until the merge to
`main`, which `helm dependency update` cannot handle.

Semantic ranges such as `^1.0.0` are rejected. A range can never equal a
resolved lock entry, so `validate-config` fails. Use exact versions!

`sync-locks` writes only the lock. If you need `charts/` populated to render or
install a chart locally, use `helm-build-chart.sh` above, which vendors them.

If validation reports that `Chart.yaml` and `Chart.lock` "dependency
name/version/repository tuples differ", this prints exactly what is being
compared:

```bash
make ci-locked-deps SERVICE=<name>
```

### Working on a service's image

Build it the way CI does:

```bash
make docker-build SERVICE=<name>
```

Bump `appVersion:` in the owning chart if you changed anything that reaches the
build context. The service's `.dockerignore` decides what that means, so if a
file never belongs in the image, add it there rather than asking for a CI
exception. Published image tags come from chart metadata (`v<appVersion>`), never
from commit messages or git tags. And if you bump `appVersion:`, you must also
bump `version:` in the owning chart.

### Pulling upstream updates

Most services are git subtrees:

```bash
make pull-user-mutator      # or pull-appstore, pull-ui, ... ; make help-subtrees lists them
make pull-remotes           # every subtree in sequence
```

`ambassador`, `pod-reaper`, and `resty` are different: they are content mirrors
of subdirectories in `helxplatform/helx-chart`, which `git subtree` cannot map.
They are copied wholesale, so **local edits to them are destroyed** on the next
pull:

```bash
make pull-resty
make pull-pod-reaper
make pull-helx-chart        # both of the above
```

The mirror refuses to clobber uncommitted work; pass `FORCE=1` to override. To
undo a pull:

```bash
git checkout HEAD -- services/resty && git clean -fd services/resty
```

After any upstream pull, run `validate-config`. An upstream chart version bump
leaves the umbrella pin stale, which is a failure this will catch.

### Deploying a branch

Every push to `develop` publishes a mutable candidate of the umbrella, pinned to
that commit's images:

```bash
helm registry login ghcr.io
helm upgrade --install helx oci://ghcr.io/helxplatform/helm-charts/helx \
  --version <umbrella-version>-develop -n <deploy-namespace>
```

It is a SemVer prerelease, so it always sorts below the matching release. To
find the version without opening the workflow run:

```bash
make ci-candidate-version
```

To reproduce what CI builds, from your branch:

```bash
make ci-build-helx-chart CHART_CHANNEL=develop
```

That vendors your branch's service charts by name, ignoring the locked versions,
and pins image tags to `develop-<short-sha>`. `CHART_CHANNEL_COMMIT` defaults to
`HEAD`. Your working tree is restored afterwards.

Note that those `develop-<sha>` images only exist if CI built that exact commit.
For deploying uncommitted work, see the next section.

### Deploying HeLx with your own build of one or more services

A Helm chart with dependencies cannot be rendered or installed from a directory
until the dependency archives are physically present in its `charts/`
subdirectory. Helm does not fetch them at install time. `make sync-locks` writes
only `Chart.lock`, which is metadata. `make ci-build-helx-chart` is what actually
vendors every dependency and produces a self-contained `.tgz` you can install
anywhere.

**If your change is already on `develop`**, do nothing locally. CI has published
a candidate with your commit's images already pinned:

```bash
helm registry login ghcr.io
helm upgrade --install helx oci://ghcr.io/helxplatform/helm-charts/helx \
  --version $(make -s ci-candidate-version) -n <deploy-namespace> \
  --values my-values.yaml
```

**For work that is not pushed yet**, build everything locally. Nothing has to
reach GitHub:

1. Make your changes, then bump the service chart `version:` and its pin in
   `deploy/helm/helx-chart/Chart.yaml`. `make ci-validate-everything` will tell
   you if you miss either one.
2. Build images for just the services you changed:

   ```bash
   make ci-build-helx-images SERVICES="user-mutator ui"
   ```

   `TAG` defaults to `test-<short-sha>` but you can override it with
   `TAG=<tag>`, just make sure to use the same tag for `ci-push-helx-images`
   and `ci-load-helx-images`. A service with several image variants, like 
   `appstore-sockets`, builds all of them. If you changed enough that listing
   them is a chore, `SERVICES=all` stands for every service that builds
   an image; it works on every step below, and cannot be combined with
   individual names.

   Images build for `linux/amd64`, the one architecture CI publishes, no matter
   what your workstation is. On Apple Silicon that means an emulated build, so
   it is slower than a native one. Override `IMAGE_PLATFORM` when the cluster
   you are aiming at is not amd64 -- a local `kind`/`minikube`/`k3d` on Apple
   Silicon wants `IMAGE_PLATFORM=linux/arm64`. Getting this wrong is not subtle:
   the pod starts and the container exits with `exec format error`.
3. Get those images to your cluster. For a local cluster, load them directly,
   no registry involved:

   ```bash
   make ci-load-helx-images SERVICES="user-mutator ui"
   ```

   `kind`, `minikube`, and `k3d` are auto-detected; override with
   `CLUSTER_TOOL=` and `CLUSTER_NAME=`. For Sterling/Azure/ASHE, push to Harbor
   instead (`docker login containers.renci.org`):

   ```bash
   make ci-push-helx-images SERVICES="user-mutator ui"
   ```

   To use a registry other than Harbor (your own ACR, a scratch project, a
   registry running beside the cluster) set `IMAGE_REGISTRY` to its base URL,
   after logging in to it:

   ```bash
   docker login myregistry.azurecr.io
   export SERVICES="user-mutator ui" IMAGE_REGISTRY=myregistry.azurecr.io/helxplatform
   make ci-build-helx-images ci-push-helx-images
   ```

   The value is a host, an optional port, and an optional project path;
   `localhost:5000` and `myregistry.azurecr.io/helxplatform` are both fine, and
   an `https://` prefix is dropped for you. Repository names are unchanged
   underneath it, so `ui` publishes as
   `myregistry.azurecr.io/helxplatform/helx-ui`.

   Because the project path is easy to forget and a missing one yields
   references nothing was ever pushed to, a remote registry not ending in
   `helxplatform` prints a warning and continues. Ignore it if you meant it. A
   `localhost` registry never warns, since those serve from their root.
   Set it on the build too: the reference is baked into the image at build
   time, so pushing with a registry the build did not use finds nothing.
4. Package the umbrella with those services pinned to your tag:

   ```bash
   make ci-build-helx-chart SERVICES="user-mutator ui"
   ```

   Every umbrella dependency already resolves from your working tree, so this
   picks up your modified charts. Passing `SERVICES` additionally writes your
   image tag into the packaged values for **only those services** — everything
   else stays on its released `v<appVersion>`. No `--set` flags needed.

   `SERVICES` rewrites image tags and nothing else. It does not set
   `enabled: true` for the services you name or `enabled: false` for the rest —
   the ones you leave out are still installed, just on their released images.
   What gets deployed is decided only by the `<name>.enabled` values in
   [`deploy/helm/helx-chart/values.yaml`](deploy/helm/helx-chart/values.yaml)
   and whatever your own `--values` file says. To install just what you
   rebuilt, turn the others off yourself at install time:

   ```bash
   helm upgrade --install helx /path/to/helx-<version>-local.tgz \
     -n <deploy-namespace> --values my-values.yaml \
     --set appstore.enabled=false --set appstore-sockets.enabled=false
   ```

   If you pushed to your own registry, pass it here as well, or the chart will
   still send the cluster to Harbor for those images:

   ```bash
   make ci-build-helx-chart SERVICES="user-mutator ui" \
     IMAGE_REGISTRY=myregistry.azurecr.io/helxplatform
   ```

   That writes both the tag and the repository for those services. Everything
   outside `SERVICES` keeps pulling from Harbor, so the cluster needs
   credentials for both registries unless you mirrored the rest yourself.
5. Install the `.tgz` it prints:

   ```bash
   helm upgrade --install helx /path/to/helx-<version>-local.tgz \
     -n <deploy-namespace> --values my-values.yaml
   ```

   Or let `make ci-helm-deploy` find that archive and your values files for
   you; see [Deploying and tearing down a local
   build](#deploying-and-tearing-down-a-local-build).

Use the same `SERVICES` and `TAG` for every step, plus the same
`IMAGE_REGISTRY` if you set one. Setting them once is easiest:

```bash
export SERVICES="user-mutator helx-ldap" \
  TAG=test-ldap-with-user-mutator-changes \
  IMAGE_REGISTRY=myregistry.azurecr.io/helxplatform
make ci-build-helx-images ci-push-helx-images ci-build-helx-chart
```

`TAG` reaches the chart only through `SERVICES`. There is no flag that retags
everything at once: with `CHART_CHANNEL` and no `SERVICES`,
`make ci-build-helx-chart` computes the tag itself as `<channel>-<short-sha>`
and ignores `TAG` entirely. To put one tag of your choosing on every image, use
`SERVICES=all`:

```bash
make ci-build-helx-chart TAG=my-tag SERVICES=all
```

`all` expands to every component with an image in
[`.github/ci/images.yaml`](.github/ci/images.yaml) — currently `appstore`,
`appstore-prepuller`, `appstore-sockets`, `ldap-sync`, `ui`, and `user-mutator`,
covering all seven images, since `appstore-sockets` owns two. It is read from
that file at run time, so a service added there is picked up without touching
the Makefile. The command prints the list it expanded to. The chart-only
dependencies `helx-ldap`, `pod-reaper`, and `resty` build no image, so nothing
pins them; they keep the tags their own charts ship. Only pin services you
actually built and pushed at that tag, or the chart will point at images that do
not exist — with `all`, that means having run the build and push steps with
`all` too.

Add `IMAGE_REGISTRY=` to that same command to point all of them somewhere other
than Harbor. Because every service is pinned, this is the one case where nothing
is left behind on Harbor, so the cluster needs credentials for your registry
only:

```bash
make ci-build-helx-chart TAG=my-tag SERVICES=all \
  IMAGE_REGISTRY=myregistry.azurecr.io/helxplatform
```

To override an image by hand instead, pass it to `helm` at install time. The
packaged `.tgz` does not have to be rebuilt — these are ordinary subchart
values, and the key is the umbrella dependency name plus the chart's own tag
key:

```text
appstore.image.tag                      ldap-sync.image.tag
appstore-sockets.image.tag              ui.image.tag
appstore-sockets.monitoring.image.tag   user-mutator.image.tag
appstore-prepuller.controller.image.tag
```

Two of those are not simply `<service-name>.image.tag` because those charts read a different key; see
`tag_path` in [`.github/ci/images.yaml`](.github/ci/images.yaml).

Each has a `repository` sibling that names the registry, so swapping
`.tag` for `.repository` in any key above gives you the other half —
`ui.image.repository`, `appstore-prepuller.controller.image.repository`, and so
on. That pair is exactly what `IMAGE_REGISTRY` writes for you.

Set them on the command line:

```bash
helm upgrade --install helx /path/to/helx-<version>.tgz -n <deploy-namespace> \
  --values my-values.yaml \
  --set ui.image.tag=my-tag \
  --set ui.image.repository=myregistry.azurecr.io/helxplatform/helx-ui \
  --set appstore-sockets.monitoring.image.tag=my-tag
```

or, better for anything you want to keep, in your own values file, where the
dependency name is a top-level key:

```yaml
ui:
  image:
    tag: my-tag
    repository: myregistry.azurecr.io/helxplatform/helx-ui
appstore-sockets:
  monitoring:
    image:
      tag: my-tag
```

Both win over whatever `ci-build-helx-chart` baked into the packaged values, so
this also works to correct a pin after the fact. The image has to already exist
at that tag in whichever registry the repository names — overriding values does
not build or push anything.

### Deploying and tearing down a local build

`make ci-helm-deploy` installs what `make ci-build-helx-chart` just packaged,
and `make ci-uninstall-release` removes an installed release along with the
storage and credentials Helm deliberately leaves behind. Both talk to whatever
cluster your current `kubectl` context points at, and both print the context and
namespace before they do anything.

#### Installing

```bash
make ci-build-helx-chart SERVICES="user-mutator ui"
make ci-helm-deploy RELEASE=helx NAMESPACE=<deploy-namespace>
```

You do not name the archive. `ci-build-helx-chart` writes its path to
`dist/charts/.helx-chart.path`, and `ci-helm-deploy` reads it from there, so
the two always agree on which build is being installed — a candidate build
derives its version from the channel and commit, so the file name is not
something you could predict anyway. If that pointer is missing, or names an
archive that has been deleted, the deploy stops and tells you to package again.

`RELEASE` defaults to `helx`. `NAMESPACE` defaults to whatever your context
selects; if it selects none either, the deploy stops rather than assuming
`default`. The namespace is created if it does not exist.

Values files come from two places, applied in this order:

1. every path listed in `deploy/local-dev/local-values-files.env`
2. every path in `VALUES="a.yaml b.yaml"`, so those win on any shared key

That first file is the point: local deploys usually need several values files,
including ones holding secrets, and retyping `--values` for each of them every
time is how they get forgotten. It is one path per line, each relative to the
repository root, with `~/` expanded for you; blank lines and `#` comments are
ignored. It is gitignored, so your cluster's paths and secrets stay out of the
repository:

```text
# deploy/local-dev/local-values-files.env
~/helm-values/my-cluster/helx/values.yaml
~/helm-values/my-cluster/appstore/secrets.yaml
```

A missing list, an empty one, or a line naming a file that is not there is a
warning rather than an error — but since the usual result is a release quietly
missing its secrets, the deploy asks before continuing. `ASSUME_YES=1` answers
that in advance for a non-interactive run, and with no terminal to ask on it
cancels instead of assuming yes.

`HELM_FLAGS` is passed through to `helm upgrade --install` last, which is how
you get a dry run:

```bash
make ci-helm-deploy RELEASE=helx NAMESPACE=<deploy-namespace> \
  HELM_FLAGS="--dry-run --debug"
```

#### Tearing down

```bash
make ci-uninstall-release RELEASE=helx NAMESPACE=<deploy-namespace>
```

`helm uninstall` on its own does not leave the namespace clean. The
chart-managed Secrets are annotated `helm.sh/resource-policy: keep`, so that
handing a Secret's ownership to `existingSecret` or External Secrets does not
delete the live credentials mid-migration. The shared user storage claim
`stdnfs` carries that same annotation, and the `data-*` claims belong to
StatefulSet `volumeClaimTemplates`, which Helm never owned in the first place.
All of that survives the uninstall and is then adopted by the next install,
which is exactly wrong when you are trying to start clean.

So this target uninstalls the release and then deletes those leftovers:

| Variable | Default |
| --- | --- |
| `UNINSTALL_PVCS` | `appstore-postgresql-pvc`, `stdnfs`, `data-$(RELEASE)-postgresql-0`, `data-$(RELEASE)-ldap-sync-postgres-0`, `data-openldap-0` |
| `UNINSTALL_SECRETS` | `$(RELEASE)-appstore-secrets`, `$(RELEASE)-appstore-sockets`, `$(RELEASE)-ldap-sync-secrets`, `$(RELEASE)-postgresql`, `openldap-credentials`, `pgadmin-env` |

`appstore-postgresql-pvc` is the one entry Helm normally deletes with the
release; it is listed so that a copy left behind by an older install goes too.

Only the names that actually exist are touched, and everything found is listed
for confirmation before anything is deleted:

```text
Uninstalling helx
  context   my-cluster
  namespace my-namespace
  release   installed
  pvcs      appstore-postgresql-pvc stdnfs data-helx-postgresql-0
  secrets   helx-appstore-secrets pgadmin-env
Deleting those claims destroys the data in them; this cannot be undone.
Proceed? [y/N]
```

`ASSUME_YES=1` skips that prompt; with no terminal to ask on, the target
cancels rather than assuming yes.

Unlike every other target here, `RELEASE` has to be named explicitly — the
`helx` default is not assumed for a command that deletes data. `NAMESPACE`
resolves exactly as it does for the deploy.

A release that is already gone is not an error: the uninstall is skipped and
only the leftovers are deleted, which is what lets this finish a teardown that
stopped halfway. If nothing is there at all, it says so and exits cleanly.

Set either variable to override the list, or to empty to leave that kind of
resource alone:

```bash
make ci-uninstall-release RELEASE=helx UNINSTALL_PVCS=
```

Two things it deliberately does not do. It deletes nothing the charts did not
create, `PersistentVolume`s included: a `Retain` volume outlives its claim, and
removing it is yours to do. And it takes no `HELM_FLAGS` — there is no dry run,
because the confirmation listing already is one.

### Working on the CI itself

The logic lives in `.github/scripts/ci.py` and is unit tested. If you change it:

```bash
make ci-tests
make ci-validate-everything
```

CI runs both before it touches a registry.

Workflow YAML itself is linted by `actionlint` in CI only — there is no local
target, since workflow files change rarely and CI gates them on every pull
request. If you are editing them often, `brew install actionlint` and run
`actionlint .github/workflows/*.yml` yourself; CI pins 1.7.12.

### Before you push

```bash
make pre-push
```

That runs the unit tests, `validate-config`, the version gate, the lock check,
and a whitespace check. To have it run automatically:

```bash
make install-hooks
```

That points `core.hooksPath` at [`.githooks/`](.githooks), so `git push` runs the
same checks. No package manager, nothing downloaded. Bypass a single push with
`git push --no-verify`, and uninstall with `git config --unset core.hooksPath`.

The umbrella chart's version only has to sit **above the last release**, not
increase on every change. So the first pull request after a release picks the
next version — patch, minor, or major, whichever fits — and later pull requests
leave it alone. Raising it starts publishing a new `<version>-develop` candidate
channel; `make ci-candidate-version` tells you which is current. Umbrella
dependency pins still have to move with the charts they point at.

The version gate compares against `develop` by default and includes uncommitted
and untracked files. That last part matters: without it a chart file you have
created but not yet committed is invisible, and a local pass can still fail in
CI. Override with `BASE=<ref>`, or `CHECK_VERSIONS_FLAGS=` for committed-only.

### Gotchas

- **Building some charts needs network.** `appstore` pulls `postgresql` from
  `charts.bitnami.com`, `helx-ldap` pulls `openldap-stack-ha` from a GitHub Pages
  repo, and `ldap-sync` pulls `postgres` from Docker Hub. Building the umbrella
  recurses into those, so it needs network too even though all of its own
  dependencies are in-tree.
- **`charts/` and `*.tgz` are generated.** They are gitignored; never commit them.
- **A published chart or image version is immutable.** Re-publishing the same
  version with different content fails the build rather than overwriting. Bump
  the version instead.
