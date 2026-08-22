#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-ai-sb-test}"
RELEASE="${2:-helx}"
CHART_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$CHART_DIR/../../.." && pwd)"
WRAPPER_DIR="$REPO_ROOT/services/helx-ldap/chart"
VALUES_FILE="$CHART_DIR/examples/ldap-test-values.yaml"

: "${LDAP_ADMIN_PASSWORD:?Set LDAP_ADMIN_PASSWORD before running this script}"
: "${LDAP_CONFIG_ADMIN_PASSWORD:?Set LDAP_CONFIG_ADMIN_PASSWORD before running this script}"

kubectl -n "$NAMESPACE" create secret generic openldap-credentials \
  --from-literal=LDAP_ADMIN_PASSWORD="${LDAP_ADMIN_PASSWORD:?Set LDAP_ADMIN_PASSWORD}" \
  --from-literal=LDAP_CONFIG_ADMIN_PASSWORD="${LDAP_CONFIG_ADMIN_PASSWORD:?Set LDAP_CONFIG_ADMIN_PASSWORD}" \
  --dry-run=client -o yaml | kubectl apply -f -

helm dependency build --skip-refresh "$WRAPPER_DIR"
helm dependency build --skip-refresh "$CHART_DIR"
helm upgrade --install "$RELEASE" "$CHART_DIR" \
  --namespace "$NAMESPACE" \
  --values "$VALUES_FILE" \
  --wait \
  --wait-for-jobs \
  --timeout 10m

kubectl -n "$NAMESPACE" rollout status statefulset/openldap --timeout=5m

helm -n "$NAMESPACE" status "$RELEASE"
kubectl -n "$NAMESPACE" get pods,svc,pvc
