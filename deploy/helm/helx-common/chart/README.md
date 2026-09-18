# helx-common

Shared Helm library templates for HeLx service charts.

## Consuming the library

Add the published library dependency to a service chart:

```yaml
dependencies:
  - name: helx-common
    version: "0.1.1"
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

### Optional arguments

`preserveKeys` selects which keys the live Secret protects. Omit it and every
persisted key wins over `values`, which is correct for a Secret holding only
generated credentials. Supply it and exactly the listed keys are preserved while
every other key tracks chart values, which is what a Secret mixing credentials
with plain configuration needs:

```gotemplate
  "preserveKeys" (list "GENERATED_PASSWORD")
```

`retain` defaults to true and controls the `helm.sh/resource-policy: keep`
annotation described below. Set it to false only for a Secret whose contents are
fully reproducible from values.

`type` sets the Kubernetes Secret type, for example `kubernetes.io/tls`.

### Ownership handoffs

The chart-managed Secret carries `helm.sh/resource-policy: keep`. Without it,
switching a chart-managed Secret to `existingSecret` or ESO under the same name
removes it from the rendered manifest and Helm deletes the live credentials
during the same upgrade, even though the workload is about to mount that name.

Helm reads that annotation from the **live** object, so it only protects a
Secret that already carries it. A handoff therefore takes two upgrades:

1. Upgrade to a chart version that renders the Secret through this helper. This
   applies the annotation to the live Secret.
2. In a later upgrade, set `existingSecret` (or enable ESO) for the same name.
   Helm leaves the live Secret in place, keeping its release ownership metadata,
   so a later return to chart-managed mode re-adopts the same object.

Handing a same-named Secret to ESO needs one extra step: an ExternalSecret with
`creationPolicy: Owner` refuses to overwrite a Secret it does not own. Either
point `externalSecret.targetName` at a new name, or delete the retained Secret
after the backend is populated and verified.

Hook-based migration templates in the service charts cannot rely on this
annotation. Helm's hook deletion path ignores `helm.sh/resource-policy`
entirely, so those templates stop rendering once the target Secret is populated
instead.

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
