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

`make help` lists every target and the environment variables each one accepts.

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
| `make docker-build SERVICE=<name>` | Build one service image as CI builds it |
| `make ci-locked-deps SERVICE=<name>` | Print that chart's resolved dependency tuples |
| `make ci-candidate-version` | Print the version the candidate channel publishes under |
| `make help` | Every target, with the variables each accepts |

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
make pull-user-mutator      # or pull-appstore, pull-ui, ... ; make help lists them
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
  --version <umbrella-version>-develop -n helx --create-namespace
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
subdirectory — Helm does not fetch them at install time. `make sync-locks` writes
only `Chart.lock`, which is metadata. `make ci-build-helx-chart` is what actually
vendors every dependency and produces a self-contained `.tgz` you can install
anywhere.

**If your change is already on `develop`**, do nothing locally. CI has published
a candidate with your commit's images already pinned:

```bash
helm registry login ghcr.io
helm upgrade --install helx oci://ghcr.io/helxplatform/helm-charts/helx \
  --version $(make -s ci-candidate-version) -n helx --create-namespace \
  --values my-values.yaml
```

**For work that is not pushed yet**, build everything locally:

1. Make your changes, then bump the service chart `version:` and its pin in
   `deploy/helm/helx-chart/Chart.yaml`. `make ci-validate-everything` will tell
   you if you miss either.
2. Build the image and get it somewhere the cluster can pull from:

   ```bash
   make docker-build SERVICE=<name>
   # hosted cluster: tag and push under a personal tag
   docker tag <image-id> containers.renci.org/helxplatform/<name>:dev-<you>-1
   docker push containers.renci.org/helxplatform/<name>:dev-<you>-1
   # local cluster instead: load it directly
   kind load docker-image <name>:latest        # or: minikube image load <name>:latest
   ```
3. Package the umbrella. Every umbrella dependency resolves from your working
   tree, so this picks up your modified service charts with no extra flags:

   ```bash
   make ci-build-helx-chart
   ```
4. Install it, overriding the image tag for each service you rebuilt:

   ```bash
   helm upgrade --install helx /path/to/helx-<version>.tgz \
     -n helx --create-namespace --values my-values.yaml \
     --set user-mutator.image.tag=dev-<you>-1
   ```

The override keys are the umbrella dependency name plus the chart's own tag key:

```text
appstore.image.tag                      ldap-sync.image.tag
appstore-sockets.image.tag              ui.image.tag
appstore-sockets.monitoring.image.tag   user-mutator.image.tag
appstore-prepuller.controller.image.tag
```

Two of those are not `image.tag` because those charts read a different key; see
`tag_path` in [`.github/ci/images.yaml`](.github/ci/images.yaml).

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
