#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  SERVICES="service-a service-b" deploy/helm/scripts/helx-local-deps.sh
  deploy/helm/scripts/helx-local-deps.sh service-a service-b
  deploy/helm/scripts/helx-local-deps.sh -all

The selected names must match local chart directories under services/<name>/chart
and dependencies declared by deploy/helm/helx-chart. -all selects every local
chart that is declared as an umbrella dependency.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v helm >/dev/null 2>&1; then
  echo "Error: helm is required but was not found in PATH." >&2
  exit 1
fi

if ! command -v yq >/dev/null 2>&1; then
  echo "Error: yq is required but was not found in PATH." >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
UMBRELLA="$REPO_ROOT/deploy/helm/helx-chart"
CHARTS_DIR="$UMBRELLA/charts"

if [[ ! -f "$UMBRELLA/Chart.yaml" ]]; then
  echo "Error: umbrella chart not found at $UMBRELLA." >&2
  exit 1
fi

# Accept either a SERVICES command-line variable, positional arguments, or
# the explicit -all mode. A missing list is an error so this script never
# unexpectedly overrides every local chart.
all_mode=0
if [[ "${1:-}" == "-all" || "${1:-}" == "--all" ]]; then
  all_mode=1
  if [[ -n "${SERVICES:-}" || $# -ne 1 ]]; then
    echo "Error: -all cannot be combined with SERVICES or service arguments." >&2
    usage >&2
    exit 1
  fi

  services=()
  for chart_dir in "$REPO_ROOT"/services/*/chart; do
    [[ -d "$chart_dir" ]] || continue
    service="${chart_dir#$REPO_ROOT/services/}"
    service="${service%/chart}"
    services+=("$service")
  done
elif [[ -n "${SERVICES:-}" && $# -gt 0 ]]; then
  echo "Error: provide services through SERVICES or positional arguments, not both." >&2
  usage >&2
  exit 1
else
  if [[ -n "${SERVICES:-}" ]]; then
    service_list="${SERVICES//,/ }"
  else
    service_list="$*"
  fi

  if [[ -z "${service_list//[[:space:],]/}" ]]; then
    echo "Error: at least one service must be selected." >&2
    usage >&2
    exit 1
  fi

  read -r -a services <<< "$service_list"
fi

if (( ${#services[@]} == 0 )); then
  echo "Error: no local service charts were found." >&2
  exit 1
fi

# Validate all selections before changing the umbrella chart. This also maps
# service directory names to chart names, which is safer than assuming they
# are identical.
declare -a selected_names=()
declare -a selected_dirs=()

for service in "${services[@]}"; do
  if [[ ! "$service" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "Error: invalid service name '$service'." >&2
    exit 1
  fi

  chart_dir="$REPO_ROOT/services/$service/chart"
  chart_yaml="$chart_dir/Chart.yaml"
  if [[ ! -f "$chart_yaml" ]]; then
    echo "Error: chart not found for service '$service' at $chart_yaml." >&2
    exit 1
  fi

  chart_name="$(yq -r '.name // ""' "$chart_yaml")"
  if [[ -z "$chart_name" ]]; then
    echo "Error: chart name is missing from $chart_yaml." >&2
    exit 1
  fi

  if ! yq -e ".dependencies[] | select(.name == \"$chart_name\")" \
    "$UMBRELLA/Chart.yaml" >/dev/null 2>&1; then
    if (( all_mode )); then
      continue
    fi
    echo "Error: chart '$chart_name' is not a dependency of the umbrella chart." >&2
    exit 1
  fi

  # Avoid rebuilding and replacing a chart twice if it was listed more than
  # once, including through a comma-separated SERVICES value. Use an indexed
  # array because macOS ships Bash 3.2, which has no associative arrays.
  duplicate=0
  if (( ${#selected_names[@]} > 0 )); then
    for selected_name in "${selected_names[@]}"; do
      if [[ "$selected_name" == "$chart_name" ]]; then
        duplicate=1
        break
      fi
    done
  fi
  if (( duplicate )); then
    continue
  fi
  selected_names+=("$chart_name")
  selected_dirs+=("$chart_dir")
done

if (( ${#selected_names[@]} == 0 )); then
  echo "Error: no local umbrella dependency charts were found." >&2
  exit 1
fi

mkdir -p "$CHARTS_DIR"

# Package selected charts before resolving the remaining umbrella dependencies.
# The temporary umbrella chart is a sibling so file://../../../services/... paths
# retain the same meaning as they do in the real umbrella chart.
package_dir="$(mktemp -d "${TMPDIR:-/tmp}/helx-local-deps.XXXXXX")"
temporary_umbrella="$(mktemp -d "$REPO_ROOT/deploy/helm/helx-chart.local-deps.XXXXXX")"
trap 'rm -rf "$package_dir" "$temporary_umbrella"' EXIT

cp -R "$UMBRELLA"/. "$temporary_umbrella"/
rm -rf "$temporary_umbrella/charts"
mkdir -p "$temporary_umbrella/charts"

remove_existing_archives() {
  local chart_name="$1"
  local archive archive_name

  for archive in "$CHARTS_DIR"/*.tgz; do
    [[ -f "$archive" ]] || continue

    # Match the chart metadata rather than only the filename. A filename glob
    # for "appstore-*" would also match "appstore-sockets-*".
    archive_name="$(helm show chart "$archive" | yq -r '.name // ""')"
    if [[ "$archive_name" == "$chart_name" ]]; then
      rm -f "$archive"
    fi
  done
}

for index in "${!selected_names[@]}"; do
  chart_name="${selected_names[$index]}"
  chart_dir="${selected_dirs[$index]}"

  echo "Building dependencies for $chart_name from ${chart_dir#$REPO_ROOT/}"
  helm dependency build "$chart_dir"

  # Helm has no "helm dependency package" command. helm package creates the
  # parent chart archive after dependency build has populated chart_dir/charts.
  chart_package_dir="$package_dir/$chart_name"
  mkdir -p "$chart_package_dir"
  helm package "$chart_dir" --destination "$chart_package_dir"

  package_files=("$chart_package_dir"/*.tgz)
  if [[ ! -f "${package_files[0]}" ]]; then
    echo "Error: helm package did not create an archive for '$chart_name'." >&2
    exit 1
  fi

  remove_existing_archives "$chart_name"
  rm -rf "$CHARTS_DIR/$chart_name"
  cp "${package_files[0]}" "$CHARTS_DIR/"
  echo "local: $chart_name <- ${package_files[0]#$chart_package_dir/}"
done

# Resolve only the dependencies that were not selected locally. Helm requires
# Chart.lock to match Chart.yaml, so regenerate a lockfile in the temporary
# sibling chart after removing the selected dependency declarations. The real
# umbrella Chart.yaml and Chart.lock are never modified.
for chart_name in "${selected_names[@]}"; do
  CHART_NAME="$chart_name" yq -i \
    'del(.dependencies[] | select(.name == strenv(CHART_NAME)))' \
    "$temporary_umbrella/Chart.yaml"
done
rm -f "$temporary_umbrella/Chart.lock"

helm dependency update --skip-refresh "$temporary_umbrella"

remaining_packages=("$temporary_umbrella/charts"/*.tgz)
if [[ -f "${remaining_packages[0]}" ]]; then
  for remaining_archive in "${remaining_packages[@]}"; do
    [[ -f "$remaining_archive" ]] || continue

    remaining_name="$(helm show chart "$remaining_archive" | yq -r '.name // ""')"
    if [[ -z "$remaining_name" ]]; then
      echo "Error: resolved archive has no chart name: $remaining_archive." >&2
      exit 1
    fi

    remove_existing_archives "$remaining_name"
    rm -rf "$CHARTS_DIR/$remaining_name"
    cp "$remaining_archive" "$CHARTS_DIR/"
    echo "dependency: $remaining_name <- ${remaining_archive#$temporary_umbrella/charts/}"
  done
fi
