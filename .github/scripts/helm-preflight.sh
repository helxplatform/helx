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

chart_field() {
  "$PYTHON" .github/scripts/ci.py chart-field "$2" "$1"
}

validate_inputs() {
  local chart_dir=$1
  local local_package=$2

  if [[ ! -f "$chart_dir/Chart.yaml" ]]; then
    echo "::error::No Chart.yaml found in $chart_dir"
    exit 1
  fi
  if [[ -n "$local_package" && ! -f "$local_package" ]]; then
    echo "::error::Local package does not exist: $local_package"
    exit 1
  fi
}

emit_publish_needed() {
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'publish-needed=%s\n' "$1" >> "$GITHUB_OUTPUT"
  fi
}

normalize_package() {
  local package=$1
  local destination=$2
  local archive nested

  mkdir -p "$destination"
  tar -xzf "$package" -C "$destination"

  # Recursively unpack dependencies so gzip timestamps cannot affect equality.
  while true; do
    archive=$(find "$destination" -type f -name '*.tgz' -print -quit)
    [[ -n "$archive" ]] || break
    nested="${archive%.tgz}.unpacked"
    mkdir -p "$nested"
    tar -xzf "$archive" -C "$nested"
    rm -f "$archive"
  done
}

check_registry() {
  local registry=$1
  local chart_name=$2
  local chart_version=$3
  local chart_ref=$4
  local output_file=$5
  local output missing_ref

  if helm show chart "$chart_ref" --version "$chart_version" >"$output_file" 2>&1; then
    rm -f "$output_file"
    return
  fi

  output=$(cat "$output_file")
  rm -f "$output_file"
  missing_ref="${chart_ref#oci://}:$chart_version: not found"
  if grep -Eqi '(manifest unknown|MANIFEST_UNKNOWN)' <<< "$output" || \
     grep -Fqi -- "$missing_ref" <<< "$output"; then
    echo "Registry preflight: $chart_name:$chart_version is not published"
    emit_publish_needed true
    exit 0
  fi

  # Any ambiguous registry failure must block publication.
  echo "::error::Could not determine whether $chart_name:$chart_version exists in $registry"
  printf '%s\n' "$output"
  exit 1
}

compare_with_published_chart() {
  local chart_name=$1
  local chart_version=$2
  local chart_ref=$3
  local local_package=$4
  local remote_dir local_dir remote_unpack local_unpack remote_package

  remote_dir=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/helm-remote.XXXXXX")
  local_dir=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/helm-local.XXXXXX")
  remote_unpack=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/helm-remote-unpack.XXXXXX")
  local_unpack=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/helm-local-unpack.XXXXXX")

  helm pull "$chart_ref" --version "$chart_version" --destination "$remote_dir"
  remote_package="$remote_dir/$chart_name-$chart_version.tgz"
  if [[ ! -f "$remote_package" ]]; then
    echo "::error::helm pull did not produce $remote_package"
    exit 1
  fi

  normalize_package "$remote_package" "$remote_unpack"
  normalize_package "$local_package" "$local_unpack"
  if diff -ru "$remote_unpack" "$local_unpack" >"$local_dir/diff"; then
    echo "Registry preflight: $chart_name:$chart_version already exists with identical content; publication will be skipped"
    emit_publish_needed false
    exit 0
  fi

  echo "::error::Chart version $chart_name:$chart_version already exists with different content"
  cat "$local_dir/diff"
  exit 1
}

main() {
  local registry=${1:?usage: helm-preflight.sh OCI_REGISTRY CHART_DIR [LOCAL_PACKAGE]}
  local chart_dir=${2:?usage: helm-preflight.sh OCI_REGISTRY CHART_DIR [LOCAL_PACKAGE]}
  local local_package=${3:-}
  local chart_name chart_version chart_ref output_file

  registry=${registry%/}
  validate_inputs "$chart_dir" "$local_package"

  chart_name=$(chart_field name "$chart_dir")
  chart_version=$(chart_field version "$chart_dir")
  chart_ref="$registry/$chart_name"
  output_file=$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/helm-preflight.XXXXXX")

  check_registry "$registry" "$chart_name" "$chart_version" "$chart_ref" "$output_file"

  if [[ -z "$local_package" ]]; then
    echo "::error::Refusing to publish immutable chart version already present in GHCR: $chart_name:$chart_version"
    exit 1
  fi

  compare_with_published_chart "$chart_name" "$chart_version" "$chart_ref" "$local_package"
}

main "$@"
