#!/usr/bin/env bash
set -euo pipefail

readonly UMBRELLA_CHART="deploy/helm/helx-chart"
shopt -s nullglob

SERVICE_CHARTS=()
ALL_CHARTS=()
validation_selected=()
publish_selected=()
changed_files=()
head_sha=""
base_sha=""

# Discover service charts from the checkout; the umbrella chart is always known.
discover_charts() {
  local chart_file
  local -a chart_files=(services/*/chart/Chart.yaml)

  for chart_file in "${chart_files[@]}"; do
    SERVICE_CHARTS+=("${chart_file%/Chart.yaml}")
  done
  ALL_CHARTS=("${SERVICE_CHARTS[@]}" "$UMBRELLA_CHART")

  readonly -a SERVICE_CHARTS
  readonly -a ALL_CHARTS
}

is_known_chart() {
  local requested=$1
  local chart

  for chart in "${ALL_CHARTS[@]}"; do
    [[ "$requested" == "$chart" ]] && return 0
  done
  return 1
}

array_contains() {
  local needle=$1
  shift
  local item

  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

json_array() {
  if (($# == 0)); then
    printf '[]'
  else
    printf '%s\n' "$@" | jq -R -s -c 'split("\n") | map(select(length > 0))'
  fi
}

local_dependency_paths() {
  local chart=$1

  python3 .github/scripts/helm_metadata.py local-dependencies "$chart"
}

has_selected_dependency() {
  local candidate=$1
  local dependency

  while IFS= read -r dependency; do
    if array_contains "$dependency" "${validation_selected[@]-}"; then
      return 0
    fi
  done < <(local_dependency_paths "$candidate")
  return 1
}

expand_reverse_dependencies() {
  local changed=true
  local candidate

  # Iterate to a fixed point so transitive file:// dependents are validated.
  while [[ "$changed" == true ]]; do
    changed=false
    for candidate in "${ALL_CHARTS[@]}"; do
      if array_contains "$candidate" "${validation_selected[@]-}"; then
        continue
      fi
      if has_selected_dependency "$candidate"; then
        validation_selected+=("$candidate")
        changed=true
        break
      fi
    done
  done
}

emit_outputs() {
  local -a publish_services=()
  local chart
  local publish_umbrella=false
  local validation_json validation_matrix publish_json publish_service_json publish_service_matrix

  for chart in "${publish_selected[@]-}"; do
    if [[ "$chart" == "$UMBRELLA_CHART" ]]; then
      publish_umbrella=true
    else
      publish_services+=("$chart")
    fi
  done

  validation_json='[]'
  publish_json='[]'
  publish_service_json='[]'
  if ((${#validation_selected[@]} > 0)); then
    validation_json=$(json_array "${validation_selected[@]}")
  fi
  if ((${#publish_selected[@]} > 0)); then
    publish_json=$(json_array "${publish_selected[@]}")
  fi
  if ((${#publish_services[@]} > 0)); then
    publish_service_json=$(json_array "${publish_services[@]}")
  fi
  validation_matrix=$validation_json
  publish_service_matrix=$publish_service_json
  [[ "$validation_matrix" == '[]' ]] && validation_matrix='["__none__"]'
  [[ "$publish_service_matrix" == '[]' ]] && publish_service_matrix='["__none__"]'

  {
    printf 'validation-charts=%s\n' "$validation_json"
    printf 'validation-matrix=%s\n' "$validation_matrix"
    printf 'publish-charts=%s\n' "$publish_json"
    printf 'publish-service-matrix=%s\n' "$publish_service_matrix"
    printf 'publish-umbrella=%s\n' "$publish_umbrella"
  } >> "${GITHUB_OUTPUT:?GITHUB_OUTPUT must be set}"
}

select_requested_charts() {
  local requested=${REQUESTED_CHART:-all}

  if [[ "$requested" == "all" ]]; then
    validation_selected=("${ALL_CHARTS[@]}")
    return
  fi
  if is_known_chart "$requested"; then
    validation_selected=("$requested")
    expand_reverse_dependencies
    return
  fi

  echo "::error::Unknown chart requested: $requested"
  echo "Use 'all' or one of: ${ALL_CHARTS[*]}"
  exit 1
}

last_marked_release_commit() {
  local revision=$1

  python3 .github/scripts/release-baseline.py --head "$revision"
}

use_protected_release_base() {
  local marked_base

  if [[ "${EVENT_NAME:-}" != push || "${REF_NAME:-}" != main ]]; then
    return
  fi

  # Protected branches accumulate changes from the last marked release.
  marked_base=$(last_marked_release_commit "$head_sha")
  if [[ -n "$marked_base" ]]; then
    base_sha=$marked_base
  fi
}

use_default_branch_base() {
  local default_branch=${DEFAULT_BRANCH:?DEFAULT_BRANCH must be set}
  local default_ref="refs/remotes/origin/$default_branch"
  local candidate

  if ! git rev-parse --verify --quiet "$default_ref^{commit}" >/dev/null; then
    default_ref="$default_branch"
  fi
  if ! git rev-parse --verify --quiet "$default_ref^{commit}" >/dev/null; then
    echo "::error::Cannot resolve the default branch '$default_branch' for change detection"
    exit 1
  fi
  if ! candidate=$(git merge-base "$default_ref" "$head_sha"); then
    echo "::error::Cannot find a merge base between $default_ref and $head_sha"
    exit 1
  fi
  if [[ "$candidate" == "$head_sha" ]] && git rev-parse --verify --quiet "$head_sha^" >/dev/null; then
    candidate=$(git rev-parse "$head_sha^")
  fi
  printf '%s\n' "$candidate"
}

resolve_comparison_base() {
  use_protected_release_base

  if [[ "${EVENT_NAME:-}" == pull_request ]]; then
    if ! base_sha=$(git merge-base "$base_sha" "$head_sha"); then
      echo "::error::Cannot find the pull-request merge base"
      exit 1
    fi
    return
  fi

  if [[ -z "$base_sha" || "$base_sha" =~ ^0+$ ]] || \
     ! git rev-parse --verify --quiet "$base_sha^{commit}" >/dev/null; then
    base_sha=$(use_default_branch_base)
  fi
}

collect_changed_files() {
  local path

  while IFS= read -r path; do
    changed_files+=("$path")
  done < <(git diff --name-only --diff-filter=ACDMRTUXB "$base_sha" "$head_sha")
}

changes_require_full_validation() {
  local path

  for path in "${changed_files[@]}"; do
    case "$path" in
      .github/actions/publish-charts/*|\
      .github/workflows/publish-charts.yml|\
      .github/scripts/helm*|\
      .github/helm/*)
        return 0
        ;;
    esac
  done
  return 1
}

select_publish_charts() {
  local chart path

  for chart in "${ALL_CHARTS[@]}"; do
    for path in "${changed_files[@]}"; do
      if [[ "$path" == "$chart/"* ]]; then
        publish_selected+=("$chart")
        break
      fi
    done
  done
}

select_validation_charts() {
  local validate_all=$1

  if [[ "$validate_all" == true ]]; then
    validation_selected=("${ALL_CHARTS[@]}")
    return
  fi

  validation_selected=("${publish_selected[@]-}")
  expand_reverse_dependencies
}

select_changed_charts() {
  local validate_all=false

  collect_changed_files
  if changes_require_full_validation; then
    validate_all=true
  fi
  select_publish_charts
  select_validation_charts "$validate_all"
}

main() {
  discover_charts

  if [[ "${EVENT_NAME:-}" == "workflow_dispatch" ]]; then
    select_requested_charts
    emit_outputs
    return
  fi

  head_sha=${AFTER_SHA:?AFTER_SHA must be set}
  base_sha=${BASE_SHA:-${BEFORE_SHA:-}}
  resolve_comparison_base
  select_changed_charts
  emit_outputs
}

main "$@"
