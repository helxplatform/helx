{{/*
Find the name of the Secret the workload should use.

Arguments:
  mode: Required. Checked by secret.mode.v1.
  defaultName: Name of the Secret created by the chart and the default ESO target.
  existingSecret: Optional name of a Secret managed outside the chart.
  externalSecret: Optional ESO settings. targetName changes the ESO target name.
  errorValuePath: Optional values path shown in error messages.
*/}}
{{- define "helx-common.secret.name.v1" -}}
{{- $defaultName := required "helx-common: secret defaultName is required" .defaultName -}}
{{- $externalSecret := default (dict) .externalSecret -}}
{{- $mode := include "helx-common.secret.mode.v1" (dict
  "mode" .mode
  "existingSecret" .existingSecret
  "externalSecret" $externalSecret
  "errorValuePath" .errorValuePath
) -}}
{{- if eq $mode "existingSecret" -}}
  {{- .existingSecret -}}
{{- else if eq $mode "externalSecret" -}}
  {{- default $defaultName (get $externalSecret "targetName") -}}
{{- else -}}
  {{- $defaultName -}}
{{- end -}}
{{- end -}}

{{/*
Check the Secret ownership settings and return the selected mode.

Arguments:
  mode: Required. One of "values", "existingSecret", "externalSecret".
  existingSecret: Optional name of a Secret managed outside the chart.
  externalSecret: Optional ESO settings.
  errorValuePath: Optional values path shown in error messages; defaults to "secret".

The caller must set the mode explicitly. This helper does not guess ownership
from the other fields, so a partially filled-in configuration cannot select a
mode by accident.

Settings for a different mode are errors. Rejecting them makes sure that no
setting is silently ignored.

Some charts build additional Secret values from other parts of their
configuration, such as a bundled database's settings. Only build those values
when this helper returns "values", because the other modes do not use them.

Always pass the user's secret.values block to resources.v1, even in the
external modes. It reports an error when values and an external owner are both
set, which exposes a conflicting configuration instead of hiding it.
*/}}
{{- define "helx-common.secret.mode.v1" -}}
{{- $errorValuePath := default "secret" .errorValuePath -}}
{{- $modes := list "values" "existingSecret" "externalSecret" -}}
{{- $mode := default "" .mode -}}
{{- $externalSecret := default (dict) .externalSecret -}}
{{- if not $mode -}}
  {{- fail (printf "helx-common: %s.mode is required; set it to one of: %s" $errorValuePath (join ", " $modes)) -}}
{{- end -}}
{{- if not (has $mode $modes) -}}
  {{- fail (printf "helx-common: %s.mode %q is not a mode; use one of: %s" $errorValuePath $mode (join ", " $modes)) -}}
{{- end -}}
{{- if and (ne $mode "existingSecret") .existingSecret -}}
  {{- fail (printf "helx-common: %s.existingSecret is set to %q but %s.mode is %q, so it would be ignored; set %s.mode to existingSecret or clear %s.existingSecret" $errorValuePath .existingSecret $errorValuePath $mode $errorValuePath $errorValuePath) -}}
{{- end -}}
{{- if and (eq $mode "existingSecret") (not .existingSecret) -}}
  {{- fail (printf "helx-common: %s.mode is existingSecret but %s.existingSecret is empty; name the Secret to use" $errorValuePath $errorValuePath) -}}
{{- end -}}
{{/*
The mode controls ownership, not externalSecret.enabled. Treat enabled: true as
an error unless the caller selected externalSecret mode, so it cannot conflict
with the selected mode.
*/}}
{{- if and (ne $mode "externalSecret") (default false (get $externalSecret "enabled")) -}}
  {{- fail (printf "helx-common: %s.externalSecret.enabled is true but %s.mode is %q; set %s.mode to externalSecret or disable it" $errorValuePath $errorValuePath $mode $errorValuePath) -}}
{{- end -}}
{{- $mode -}}
{{- end -}}

{{/*
Build the data for a Secret managed by the chart.

Arguments:
  root: Root context for the calling chart.
  targetName: Name of the Secret managed by the chart.
  values: Plaintext fallback values written to stringData.
  migration: Optional settings for a legacy Secret: legacyName, annotation, and keyRenames.
  preserveKeys: Optional list of saved keys to keep.

Saved target and legacy values are base64-encoded Secret data. Values are used
only when there is no saved value for that key.

Without preserveKeys, every saved key wins over values. This works well for a
Secret that contains only generated credentials. With preserveKeys, only the
listed saved keys win; the rest follow the values in the chart. Use this when a
Secret contains both credentials and regular configuration.
*/}}
{{- define "helx-common.secret.payload.v1" -}}
{{- $root := required "helx-common: secret root context is required" .root -}}
{{- $targetName := required "helx-common: secret targetName is required" .targetName -}}
{{- $migration := default (dict) .migration -}}
{{- $legacyName := default "" (get $migration "legacyName") -}}
{{- $migrationAnnotation := default "secrets.helxplatform.io/migrated-from" (get $migration "annotation") -}}
{{- $keyRenames := default (dict) (get $migration "keyRenames") -}}

{{/* On a new install, do not read Secrets that may already exist in the cluster. */}}
{{- $targetSecret := dict -}}
{{- $legacySecret := dict -}}
{{- if $root.Release.IsUpgrade -}}
  {{- $targetSecret = lookup "v1" "Secret" $root.Release.Namespace $targetName -}}
  {{- if and $legacyName (ne $legacyName $targetName) -}}
    {{- $legacySecret = lookup "v1" "Secret" $root.Release.Namespace $legacyName -}}
  {{- end -}}
{{- end -}}

{{/* Copy the sources because normalizing key names changes each map. */}}
{{- $targetData := deepCopy (default (dict) $targetSecret.data) -}}
{{- $legacyData := deepCopy (default (dict) $legacySecret.data) -}}
{{- $valuesData := dict -}}
{{- range $key, $value := (default (dict) .values) -}}
  {{- $_ := set $valuesData $key (toString $value) -}}
{{- end -}}

{{/* Rename keys in each source before merging so the intended priority is kept. */}}
{{- range $source := list $targetData $legacyData $valuesData -}}
  {{- range $oldKey, $newKey := $keyRenames -}}
    {{- if hasKey $source $oldKey -}}
      {{- if not (hasKey $source $newKey) -}}
        {{- $_ := set $source $newKey (get $source $oldKey) -}}
      {{- end -}}
      {{- $_ := unset $source $oldKey -}}
    {{- end -}}
  {{- end -}}
{{- end -}}

{{- $existingAnnotations := dict -}}
{{- if and $targetSecret $targetSecret.metadata $targetSecret.metadata.annotations -}}
  {{- $existingAnnotations = $targetSecret.metadata.annotations -}}
{{- end -}}
{{- $wasMigrated := and $legacyName (hasKey $existingAnnotations $migrationAnnotation) -}}

{{- $annotations := dict -}}
{{- $data := dict -}}
{{- if $wasMigrated -}}
  {{/* This target was migrated before, so its data wins and legacy data fills missing keys. */}}
  {{- $_ := set $annotations $migrationAnnotation (get $existingAnnotations $migrationAnnotation) -}}
  {{- $data = mergeOverwrite (dict) $legacyData $targetData -}}
{{- else if $legacySecret -}}
  {{/* On the first migration, legacy data wins over data already in the target. */}}
  {{- $_ := set $annotations $migrationAnnotation $legacyName -}}
  {{- $data = mergeOverwrite (dict) $targetData $legacyData -}}
{{- else -}}
  {{- $data = $targetData -}}
{{- end -}}

{{/* Keys not in preserveKeys use the current values instead of saved data. */}}
{{- if hasKey . "preserveKeys" -}}
  {{- $preserveKeys := default (list) .preserveKeys -}}
  {{- range $key, $value := $valuesData -}}
    {{- if not (has $key $preserveKeys) -}}
      {{- $_ := unset $data $key -}}
    {{- end -}}
  {{- end -}}
{{- end -}}

{{- $stringData := dict -}}
{{- range $key, $value := $valuesData -}}
  {{- if not (hasKey $data $key) -}}
    {{- $_ := set $stringData $key $value -}}
  {{- end -}}
{{- end -}}

annotations:
{{ toYaml $annotations | nindent 2 }}
data:
{{ toYaml $data | nindent 2 }}
stringData:
{{ toYaml $stringData | nindent 2 }}
{{- end -}}

{{/*
Render the resources for a Secret with one of three ownership modes.

Arguments:
  root: Root context for the calling chart.
  mode: Required. The ownership mode, checked by secret.mode.v1.
  errorValuePath: Optional values path shown in error messages; defaults to "secret".
  defaultName: Default name of the Secret. Chart-managed mode creates it, and
    ESO uses it unless externalSecret.targetName overrides it.
  existingSecret: Optional name of a Secret managed outside the chart.
  values: Plaintext values for a chart-managed Secret. They are valid only in
    values mode. Pull values from elsewhere in the values file only after
    you've called secret.mode.v1 to verify that values mode is enabled.
  externalSecret: ESO settings: enabled, refreshInterval, secretStoreRef, and remoteRef.
  externalSecretName: Optional ExternalSecret resource name; defaults to defaultName.
  migration: Optional migration settings for secret.payload.v1.
  preserveKeys: Optional list for secret.payload.v1.
  requiredKeys: Optional list of keys that must be non-empty in the final Secret data.
  type: Optional Secret type; defaults to Opaque.
  retain: Optional boolean; defaults to true.

By default, a chart-managed Secret gets helm.sh/resource-policy: keep. This
prevents Helm from deleting it when ownership changes to existingSecret or ESO
with the same name. Helm reads the annotation from the live Secret, so first
upgrade to a chart that adds it. Change ownership in a later upgrade. Set
retain to false only when the Secret can be recreated entirely from values.
*/}}
{{- define "helx-common.secret.resources.v1" -}}
{{- $root := required "helx-common: secret root context is required" .root -}}
{{- $defaultName := required "helx-common: secret defaultName is required" .defaultName -}}
{{- $existingSecret := default "" .existingSecret -}}
{{- $externalSecret := default (dict) .externalSecret -}}
{{- $externalTargetName := default $defaultName (get $externalSecret "targetName") -}}
{{- $secretType := default "Opaque" (get . "type") -}}
{{- $retain := true -}}
{{- if hasKey . "retain" -}}
  {{- $retain = .retain -}}
{{- end -}}
{{- $mode := include "helx-common.secret.mode.v1" (dict
  "mode" .mode
  "existingSecret" $existingSecret
  "externalSecret" $externalSecret
  "errorValuePath" .errorValuePath
) -}}
{{/*
Fail if values were passed for a mode that will not use them. This usually means
the configuration names two Secret owners, or the chart derived values from a
values file without checking secret.mode.v1 first.
*/}}
{{- if and (ne $mode "values") (default (dict) .values) -}}
  {{- $errorValuePath := default "secret" .errorValuePath -}}
  {{- fail (printf "helx-common: values were supplied for Secret %s but %s.mode is %q, so they would be silently discarded. Clear %s.values, or set %s.mode to values. A chart deriving values from configuration outside its secret block must gate that derivation on helx-common.secret.mode.v1." $defaultName $errorValuePath $mode $errorValuePath $errorValuePath) -}}
{{- end -}}
{{- if eq $mode "values" -}}
  {{- $payloadArgs := dict
    "root" $root
    "targetName" $defaultName
    "values" (default (dict) .values)
    "migration" (default (dict) .migration)
  -}}
  {{- if hasKey . "preserveKeys" -}}
    {{- $_ := set $payloadArgs "preserveKeys" (default (list) .preserveKeys) -}}
  {{- end -}}
  {{- $payload := include "helx-common.secret.payload.v1" $payloadArgs | fromYaml -}}
  {{- $data := default (dict) $payload.data -}}
  {{- $stringData := default (dict) $payload.stringData -}}
  {{- range $key := (default (list) .requiredKeys) -}}
    {{- $encodedValue := default "" (get $data $key) -}}
    {{- $literalValue := default "" (get $stringData $key) -}}
    {{- if and (empty $encodedValue) (empty $literalValue) -}}
      {{- fail (printf "helx-common: chart-managed Secret %s requires non-empty key %s in persisted data or secret.values" $defaultName $key) -}}
    {{- end -}}
  {{- end -}}
  {{- $annotations := deepCopy (default (dict) $payload.annotations) -}}
  {{- if $retain -}}
    {{- $_ := set $annotations "helm.sh/resource-policy" "keep" -}}
  {{- end -}}
apiVersion: v1
kind: Secret
metadata:
  name: {{ $defaultName }}
{{- with $annotations }}
  annotations:
{{- toYaml . | nindent 4 }}
{{- end }}
type: {{ $secretType }}
{{- with $payload.data }}
data:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- with $payload.stringData }}
stringData:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{- if eq $mode "externalSecret" }}
  {{- $secretStoreRef := default (dict) (get $externalSecret "secretStoreRef") -}}
  {{- $remoteRef := required "helx-common: secret.externalSecret.remoteRef is required" (get $externalSecret "remoteRef") -}}
apiVersion: {{ default "external-secrets.io/v1" (get $externalSecret "apiVersion") }}
kind: ExternalSecret
metadata:
  name: {{ default $defaultName .externalSecretName }}
spec:
  refreshInterval: {{ default "1h" (get $externalSecret "refreshInterval") }}
  secretStoreRef:
    name: {{ required "helx-common: secret.externalSecret.secretStoreRef.name is required" (get $secretStoreRef "name") }}
    kind: {{ default "SecretStore" (get $secretStoreRef "kind") }}
  target:
    name: {{ $externalTargetName }}
    creationPolicy: {{ default "Owner" (get $externalSecret "creationPolicy") }}
    {{- if ne $secretType "Opaque" }}
    template:
      type: {{ $secretType }}
    {{- end }}
  dataFrom:
    - extract:
        key: {{ $remoteRef }}
{{- end -}}

{{/* Keep a separate legacy Secret while the Helm migration is underway. */}}
{{- $migration := default (dict) .migration -}}
{{- $legacyName := default "" (get $migration "legacyName") -}}
{{- if and (eq $mode "values") $root.Release.IsUpgrade $legacyName (ne $legacyName $defaultName) -}}
  {{- $legacySecret := lookup "v1" "Secret" $root.Release.Namespace $legacyName -}}
  {{- if $legacySecret }}
---
apiVersion: v1
kind: Secret
metadata:
  name: {{ $legacyName }}
  annotations:
    helm.sh/resource-policy: keep
type: {{ default "Opaque" $legacySecret.type }}
{{- with $legacySecret.data }}
data:
{{- toYaml . | nindent 2 }}
{{- end }}
  {{- end -}}
{{- end -}}
{{- end -}}
