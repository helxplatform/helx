#!/usr/bin/env bash
set -euo pipefail

# Interpreter used for ci.py. Prefers the project virtualenv so this script
# works whether or not the venv is activated in your shell; override with
# PYTHON=... to use your own.
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "${VENV:-.venv}/bin/python" ]]; then
    PYTHON="${VENV:-.venv}/bin/python"
  else
    PYTHON=python3
  fi
fi
readonly PYTHON

readonly COMMON_CHART="deploy/helm/helx-common/chart"
readonly UMBRELLA_CHART="deploy/helm/helx-chart"

# Candidate channels publish a mutable prerelease chart that tracks a branch.
# In this mode local charts win over locked versions and images are pinned to
# the commit being built, so the archive always describes the current tree.
readonly CHANNEL="${CHART_CHANNEL:-}"
readonly CHANNEL_COMMIT="${CHART_CHANNEL_COMMIT:-}"

candidate_mode() {
  [[ -n "$CHANNEL" ]]
}

chart_field() {
  "$PYTHON" .github/scripts/ci.py chart-field "$1" "$2"
}

locked_dependencies() {
  "$PYTHON" .github/scripts/ci.py locked-dependencies "$1"
}

find_local_chart() {
  local name=$1
  local version=$2
  local chart_file candidate
  local -a chart_files=("$COMMON_CHART/Chart.yaml" services/*/chart/Chart.yaml)

  for chart_file in "${chart_files[@]}"; do
    [[ -f "$chart_file" ]] || continue
    candidate=${chart_file%/Chart.yaml}
    [[ "$(chart_field "$candidate" name)" == "$name" ]] || continue
    if candidate_mode || [[ "$(chart_field "$candidate" version)" == "$version" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 0
}

resolve_file_dependency() {
  local chart_dir=$1
  local repository=$2
  local relative=${repository#file://}

  if [[ ! -d "$chart_dir/$relative" ]]; then
    echo "::error::Local dependency does not exist: $chart_dir/$relative" >&2
    return 1
  fi
  (cd "$chart_dir/$relative" && pwd)
}

pull_dependency() {
  local destination=$1
  local name=$2
  local version=$3
  local repository=$4
  local alias=$5

  case "$repository" in
    oci://*)
      helm pull "${repository%/}/$name" --version "$version" --destination "$destination"
      ;;
    http://*|https://*)
      helm repo add "$alias" "$repository" --force-update
      helm pull "$alias/$name" --version "$version" --destination "$destination"
      ;;
    *)
      echo "::error::Unsupported dependency repository for $name: $repository" >&2
      return 1
      ;;
  esac
}

prepare_dependencies() {
  local chart_dir=$1
  local rows name version repository source alias
  local repository_index=0

  # Always remove stale vendored archives, including when a chart no longer has dependencies.
  mkdir -p "$chart_dir/charts"
  find "$chart_dir/charts" -maxdepth 1 -type f -name '*.tgz' -delete

  # This command also verifies that Chart.lock exactly matches Chart.yaml.
  rows=$(locked_dependencies "$chart_dir")
  [[ -n "$rows" ]] || return 0

  while IFS=$'\t' read -r name version repository; do
    [[ -n "$name" ]] || continue
    source=""
    if [[ "$repository" == file://* ]]; then
      source=$(resolve_file_dependency "$chart_dir" "$repository")
    else
      source=$(find_local_chart "$name" "$version")
    fi

    if [[ -n "$source" ]]; then
      prepare_dependencies "$source"
      helm package "$source" --destination "$chart_dir/charts"
      continue
    fi

    repository_index=$((repository_index + 1))
    alias="ci-${repository_index}-$(printf '%s' "$name" | tr '/_' '--')"
    pull_dependency "$chart_dir/charts" "$name" "$version" "$repository" "$alias"
  done <<< "$rows"
}

apply_candidate_values() {
  local chart_dir=$1
  local values="$chart_dir/values.yaml"
  local backup_dir backup

  if [[ ! -f "$values" ]]; then
    echo "::error::Candidate chart has no values.yaml: $values" >&2
    return 1
  fi

  # helm package cannot take value overrides, so the working tree is edited and
  # restored on exit rather than leaving the candidate tags behind. The backup
  # must live outside the chart or helm package would ship it in the archive.
  backup_dir=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/helm-values.XXXXXX")
  backup="$backup_dir/values.yaml"
  cp "$values" "$backup"
  # shellcheck disable=SC2064
  trap "mv -f '$backup' '$values'; rmdir '$backup_dir' 2>/dev/null || true" EXIT

  "$PYTHON" .github/scripts/ci.py candidate-values \
    --channel "$CHANNEL" \
    --commit "$CHANNEL_COMMIT" \
    --merge-into "$values"
}

lint_chart() {
  local chart_dir=$1
  local chart_name=$2
  local values_file=".github/helm/lint-values/$chart_name.yaml"
  local -a arguments=("$chart_dir")

  [[ -f "$values_file" ]] && arguments+=(--values "$values_file")
  helm lint "${arguments[@]}"
}

package_chart() {
  local chart_dir=$1
  local chart_name=$2
  local chart_version=$3
  local package_dir package

  package_dir=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/helm-package.XXXXXX")
  if candidate_mode; then
    helm package "$chart_dir" --destination "$package_dir" --version "$chart_version"
  else
    helm package "$chart_dir" --destination "$package_dir"
  fi
  package="$package_dir/$chart_name-$chart_version.tgz"
  [[ -f "$package" ]] || {
    echo "::error::helm package did not create $package" >&2
    return 1
  }

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

  [[ "$chart_dir" != *..* && -f "$chart_dir/Chart.yaml" ]] || {
    echo "::error::Invalid chart directory: $chart_dir" >&2
    exit 1
  }

  chart_name=$(chart_field "$chart_dir" name)
  chart_version=$(chart_field "$chart_dir" version)
  prepare_dependencies "$chart_dir"

  if candidate_mode; then
    if [[ -z "$CHANNEL_COMMIT" ]]; then
      echo "::error::CHART_CHANNEL requires CHART_CHANNEL_COMMIT" >&2
      exit 1
    fi
    # Candidate value overrides are umbrella-shaped, so refuse any other chart.
    if [[ "${chart_dir%/}" != "$UMBRELLA_CHART" ]]; then
      echo "::error::CHART_CHANNEL only applies to $UMBRELLA_CHART, not $chart_dir" >&2
      exit 1
    fi
    chart_version=$("$PYTHON" .github/scripts/ci.py candidate-version \
      --channel "$CHANNEL" --chart-dir "$chart_dir")
    apply_candidate_values "$chart_dir"
  fi

  lint_chart "$chart_dir" "$chart_name"
  package_chart "$chart_dir" "$chart_name" "$chart_version"
}

main "$@"
