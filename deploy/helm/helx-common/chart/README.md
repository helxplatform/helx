# helx-common

Shared Helm library templates for HeLx service charts.

## Consuming the library

Add the published library dependency to a service chart:

```yaml
dependencies:
  - name: helx-common
    version: "0.1.0"
    repository: "oci://ghcr.io/helxplatform/helm-charts"
```

Commit the resulting `Chart.lock`, but do not commit generated dependency
archives under `charts/`. CI publishes `helx-common` before service charts. For
pull requests and first publication of a new version, CI substitutes an exact
name-and-version match from this repository while assembling dependencies; the
committed metadata remains OCI-based.

## Secret helpers

`helx-common.secret.resources.v1` implements one Secret contract with three
mutually exclusive ownership modes:

1. A chart-managed Secret bootstrapped from values.
2. A caller-managed Secret selected with `existingSecret`.
3. An ESO-managed Secret selected with `secret.externalSecret.enabled`.

It also supports optional cluster-aware migration from a differently named
legacy Secret. Persisted data is normalized using caller-provided key renames,
and values only fill keys absent from persisted data.

Consumers use one standard values block:

```yaml
secret:
  existingSecret: ""
  values: {}
  externalSecret:
    enabled: false
    targetName: ""
    refreshInterval: 1h
    secretStoreRef:
      name: vault
      kind: SecretStore
    remoteRef: ""
  migration:
    enabled: false
```

A consumer renders resources by passing its chart context and service-specific
configuration explicitly:

```gotemplate
{{- $migration := dict -}}
{{- if .Values.secret.migration.enabled -}}
  {{- $migration = dict
    "legacyName" (include "example.fullname" .)
    "annotation" "example.helxplatform.io/migrated-from"
    "keyRenames" (dict "OLD_KEY" "NEW_KEY")
  -}}
{{- end -}}
{{- include "helx-common.secret.resources.v1" (dict
  "root" .
  "defaultName" (printf "%s-secrets" (include "example.fullname" .))
  "existingSecret" .Values.secret.existingSecret
  "values" .Values.secret.values
  "externalSecret" .Values.secret.externalSecret
  "externalSecretName" (include "example.fullname" .)
  "migration" $migration
  "requiredKeys" (list "EXAMPLE_API_KEY")
) -}}
```

Set `secret.externalSecret.targetName` when ESO should use a target distinct
from the chart-managed Secret, for example during an explicit ownership
handoff.

Workloads resolve the selected name with:

```gotemplate
{{- include "helx-common.secret.name.v1" (dict
  "defaultName" (printf "%s-secrets" (include "example.fullname" .))
  "existingSecret" .Values.secret.existingSecret
  "externalSecret" .Values.secret.externalSecret
) -}}
```

`requiredKeys` validates non-empty keys after persisted data, migration data,
and values have been merged. It is skipped for ESO and `existingSecret` because
Helm cannot inspect those external data sources reliably during rendering.

The chart-managed persistence and migration paths use Helm `lookup` only when
`.Release.IsUpgrade` is true. They therefore require a cluster-aware Helm
upgrade and must not be relied on to preserve generated or migrated values
during Argo CD's client-side Helm rendering. Under Argo CD, provide stable
values explicitly or prefer ESO/`existingSecret`. Those external modes never
run migration lookups.
