# Helm helper scripts

## `helx-local-deps.sh`

`helx-local-deps.sh` prepares local service charts for use as dependencies of
`deploy/helm/helx-chart`.

The umbrella chart normally resolves its dependencies from the configured OCI
registry. This script lets local chart sources override that behavior for an
explicit set of services:

1. Runs `helm dependency build` in each selected local service chart.
2. Packages each selected service chart with `helm package` and copies its
   archive into `deploy/helm/helx-chart/charts/`.
3. Creates a temporary sibling copy of the umbrella chart, removes the selected
   dependencies from its `Chart.yaml`, and regenerates its temporary lockfile.
4. Resolves only the remaining umbrella dependencies and copies those archives
   into `deploy/helm/helx-chart/charts/`.

The temporary chart preserves the umbrella chart's relative
`file://../../../services/...` dependency paths. Since Helm rejects a lockfile
that does not match the temporary `Chart.yaml`, the script regenerates the
lockfile only in that copy. The umbrella currently declares exact dependency
versions, so the regenerated lockfile retains those pinned versions. The real
umbrella `Chart.yaml` and `Chart.lock` are not modified.

The script uses `helm package` for chart archives; Helm does not provide a
`helm dependency package` command.

### Prerequisites

- Run from this repository, or from a directory inside its Git worktree.
- Bash.
- Helm 3.
- [`yq`](https://mikefarah.gitbook.io/yq/) on `PATH`.
- Access and authentication for any OCI or HTTP repositories needed by the
  remaining umbrella dependencies or selected service dependencies.

Selected local charts are packaged before the remaining umbrella dependencies
are resolved. Their corresponding OCI packages therefore do not need to exist
remotely for this script to work. Remote-only dependencies are still resolved
from their configured repositories and require the appropriate registry or
repository authentication.

### Usage

Pass service directory names as positional arguments:

```sh
./deploy/helm/scripts/helx-local-deps.sh appstore ui
```

Alternatively, use the `SERVICES` variable. Space-separated and comma-separated
lists are accepted:

```sh
SERVICES="appstore ui" ./deploy/helm/scripts/helx-local-deps.sh
SERVICES="appstore,ui" ./deploy/helm/scripts/helx-local-deps.sh
```

To override every local chart that is also declared as a dependency of the
umbrella chart, use `-all`:

```sh
./deploy/helm/scripts/helx-local-deps.sh -all
```

`--all` is accepted as an alias. `-all` cannot be combined with `SERVICES` or
positional service names.

For explicit selections, each service must have a chart at
`services/<service>/chart`, and its chart name must be declared in the
umbrella's `Chart.yaml`. In `-all` mode, local charts that are not umbrella
dependencies are skipped.

### Generated files and side effects

The script generates dependency archives in the selected service chart's
`charts/` directory, uses a temporary sibling copy of the umbrella chart while
resolving the remaining dependencies, and replaces the corresponding archives
in `deploy/helm/helx-chart/charts/`. These archives are ignored by Git and
should not normally be committed. The temporary umbrella copy and its generated
lockfile are removed automatically.

Because dependency resolution can download charts, run the script after
logging in to the required registries and repositories. Re-run it whenever a
selected local chart or one of its dependencies changes.
