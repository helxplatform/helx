#!/usr/bin/env bash
set -euo pipefail

chart_field() {
  local field=$1
  local chart=$2
  awk -v field="$field" '$1 == field ":" { gsub(/["'\'']/, "", $2); print $2; exit }' \
    "$chart/Chart.yaml"
}

validate_chart_dir() {
  local chart_dir=$1

  if [[ "$chart_dir" == *".."* ]]; then
    echo "::error::Chart path may not traverse upward: $chart_dir"
    exit 1
  fi
  if [[ ! -f "$chart_dir/Chart.yaml" ]]; then
    echo "::error::No Chart.yaml found in $chart_dir"
    exit 1
  fi
}

has_dependencies() {
  awk '
    /^dependencies:[[:space:]]*($|#)/ { in_dependencies=1; next }
    in_dependencies && /^[^[:space:]#]/ { in_dependencies=0 }
    in_dependencies && /^[[:space:]]*-[[:space:]]+name:/ { found=1 }
    END { exit(found ? 0 : 1) }
  ' "$1/Chart.yaml"
}

require_dependency_lock() {
  local chart=$1
  local message=$2

  if [[ ! -f "$chart/Chart.lock" ]]; then
    echo "::error file=$chart/Chart.yaml::$message"
    exit 1
  fi
}

register_locked_http_repositories() {
  local dependency_chart=$1
  local repository repository_alias
  local repository_index=0

  # Register only lockfile URLs; dependency build must not recalculate versions.
  while IFS= read -r repository; do
    case "$repository" in
      http://*|https://*)
        repository_index=$((repository_index + 1))
        repository_alias=$(printf 'ci-%s-%d' "$dependency_chart" "$repository_index" | tr '/_' '--')
        helm repo add "$repository_alias" "$repository" --force-update
        ;;
    esac
  done < <(
    awk '$1 == "repository:" { gsub(/["'\'']/, "", $2); if (!seen[$2]++) print $2 }' \
      "$dependency_chart/Chart.lock"
  )
}

build_dependencies() {
  local dependency_chart=$1

  if ! has_dependencies "$dependency_chart"; then
    return
  fi

  require_dependency_lock \
    "$dependency_chart" \
    "Chart declares dependencies but $dependency_chart/Chart.lock is missing. Commit a lockfile generated for these dependencies."
  register_locked_http_repositories "$dependency_chart"

  echo "Building dependencies from $dependency_chart/Chart.lock"
  helm dependency build "$dependency_chart"
}

locked_dependencies() {
  local umbrella=$1

  python3 .github/scripts/helm_metadata.py locked-dependencies \
    "$umbrella/Chart.yaml" "$umbrella/Chart.lock"
}

find_local_dependency_source() {
  local umbrella=$1
  local name=$2
  local version=$3
  local repository=$4
  local source_file candidate source_name source_version

  if [[ "$repository" == file://* ]]; then
    python3 .github/scripts/helm_metadata.py resolve-file "$umbrella" "$repository"
    return
  fi

  for source_file in services/*/chart/Chart.yaml; do
    candidate=${source_file%/Chart.yaml}
    source_name=$(chart_field name "$candidate")
    source_version=$(chart_field version "$candidate")
    if [[ "$source_name" == "$name" && "$source_version" == "$version" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  return 0
}

package_local_dependency() {
  local umbrella=$1
  local source=$2
  local name=$3
  local version=$4

  if [[ ! -f "$source/Chart.yaml" ]]; then
    echo "::error::Locked local dependency $name:$version does not exist at $source"
    exit 1
  fi
  if [[ "$(chart_field name "$source")" != "$name" || \
        "$(chart_field version "$source")" != "$version" ]]; then
    echo "::error::Local dependency $source does not match locked $name:$version"
    exit 1
  fi

  build_dependencies "$source"
  helm package "$source" --destination "$umbrella/charts"
}

pull_locked_dependency() {
  local umbrella=$1
  local name=$2
  local version=$3
  local repository=$4
  local repository_alias=$5

  case "$repository" in
    oci://*)
      helm pull "${repository%/}/$name" --version "$version" --destination "$umbrella/charts"
      ;;
    http://*|https://*)
      helm repo add "$repository_alias" "$repository" --force-update
      helm pull "$repository_alias/$name" --version "$version" --destination "$umbrella/charts"
      ;;
    *)
      echo "::error::Unsupported locked dependency repository for $name: $repository"
      exit 1
      ;;
  esac
}

assemble_umbrella_dependencies() {
  local umbrella=$1
  local name version repository source repository_alias
  local repository_index=0
  local dependency_count=0

  require_dependency_lock \
    "$umbrella" \
    "Chart declares dependencies but $umbrella/Chart.lock is missing. Commit the lockfile."

  mkdir -p "$umbrella/charts"
  find "$umbrella/charts" -maxdepth 1 -type f -name '*.tgz' -delete

  # Prefer matching local service sources; pull only dependencies unavailable locally.
  while IFS=$'\t' read -r name version repository; do
    dependency_count=$((dependency_count + 1))
    source=$(find_local_dependency_source "$umbrella" "$name" "$version" "$repository")

    if [[ -n "$source" ]]; then
      package_local_dependency "$umbrella" "$source" "$name" "$version"
      continue
    fi

    repository_alias=""
    if [[ "$repository" == http://* || "$repository" == https://* ]]; then
      repository_index=$((repository_index + 1))
      repository_alias="umbrella-ci-$repository_index"
    fi
    pull_locked_dependency "$umbrella" "$name" "$version" "$repository" "$repository_alias"
  done < <(locked_dependencies "$umbrella")

  if ((dependency_count == 0)); then
    echo "::error::No valid locked umbrella dependencies were assembled"
    exit 1
  fi
}

prepare_dependencies() {
  local chart_dir=$1

  if [[ "$chart_dir" == "deploy/helm/helx-chart" ]]; then
    assemble_umbrella_dependencies "$chart_dir"
  else
    build_dependencies "$chart_dir"
  fi
}

lint_chart() {
  local chart_dir=$1
  local chart_name=$2
  local lint_values=".github/helm/lint-values/$chart_name.yaml"
  local -a lint_args=("$chart_dir")

  if [[ -f "$lint_values" ]]; then
    lint_args+=(--values "$lint_values")
  fi
  helm lint "${lint_args[@]}"
}

package_and_emit_outputs() {
  local chart_dir=$1
  local chart_name=$2
  local chart_version=$3
  local package_dir package

  package_dir=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/helm-package.XXXXXX")
  helm package "$chart_dir" --destination "$package_dir"
  package="$package_dir/$chart_name-$chart_version.tgz"
  if [[ ! -f "$package" ]]; then
    echo "::error::helm package did not create the expected archive $package"
    exit 1
  fi

  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
      printf 'chart-name=%s\n' "$chart_name"
      printf 'chart-version=%s\n' "$chart_version"
      printf 'package=%s\n' "$package"
    } >> "$GITHUB_OUTPUT"
  else
    printf '%s\n' "$package"
  fi
}

main() {
  local chart_dir=${1:?usage: helm-build-chart.sh CHART_DIR}
  local chart_name chart_version

  validate_chart_dir "$chart_dir"
  prepare_dependencies "$chart_dir"

  chart_name=$(chart_field name "$chart_dir")
  chart_version=$(chart_field version "$chart_dir")
  if [[ -z "$chart_name" || -z "$chart_version" ]]; then
    echo "::error file=$chart_dir/Chart.yaml::Chart name and version are required"
    exit 1
  fi

  lint_chart "$chart_dir" "$chart_name"
  package_and_emit_outputs "$chart_dir" "$chart_name" "$chart_version"
}

main "$@"
