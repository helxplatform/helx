# Helm helper scripts

## `helx-local-deps.sh`

`helx-local-deps.sh` prepares local service charts for use as dependencies of
`deploy/helm/helx-chart`.

The umbrella chart normally resolves its dependencies from the configured OCI
registry. This script lets local chart sources override that behavior for an
explicit set of services:

1. Builds the umbrella chart's normal dependencies from `Chart.lock`.
2. Runs `helm dependency build` in each selected local service chart.
3. Packages each selected service chart with `helm package`.
4. Replaces only the corresponding chart archive in
   `deploy/helm/helx-chart/charts/`.

The script uses `helm package` for chart archives; Helm does not provide a
`helm dependency package` command.

### Prerequisites

- Run from this repository, or from a directory inside its Git worktree.
- Bash.
- Helm 3.
- [`yq`](https://mikefarah.gitbook.io/yq/) on `PATH`.
- Access and authentication for any OCI or HTTP repositories needed by the
  umbrella chart or selected service dependencies.

The script builds the umbrella dependencies first, so remote-only dependencies
are still available. For example, `search` is an umbrella dependency without a
corresponding local chart and remains resolved from the OCI registry.

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
`charts/` directory and replaces the selected archives in
`deploy/helm/helx-chart/charts/`. These archives are ignored by Git and should
not normally be committed.

Because dependency resolution can download charts, run the script after
logging in to the required registries and repositories. Re-run it whenever a
selected local chart or one of its dependencies changes.
