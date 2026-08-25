{{/*
Resolve the Secret consumed by a workload.

Arguments:
  defaultName: Name of the chart-managed Secret and default ESO target.
  existingSecret: Optional caller-managed Secret name.
  externalSecret: Optional ESO settings; targetName overrides the ESO target.
*/}}
{{- define "helx-common.secret.name.v1" -}}
{{- $defaultName := required "helx-common: secret defaultName is required" .defaultName -}}
{{- $externalSecret := default (dict) .externalSecret -}}
{{- $externalEnabled := default false (get $externalSecret "enabled") -}}
{{- if .existingSecret -}}
  {{- .existingSecret -}}
{{- else if $externalEnabled -}}
  {{- default $defaultName (get $externalSecret "targetName") -}}
{{- else -}}
  {{- $defaultName -}}
{{- end -}}
{{- end -}}

{{/* Validate that exactly one external ownership mode is selected. */}}
{{- define "helx-common.secret.validate.v1" -}}
{{- $externalSecret := default (dict) .externalSecret -}}
{{- if and .existingSecret (default false (get $externalSecret "enabled")) -}}
  {{- fail "helx-common: secret.existingSecret and secret.externalSecret.enabled are mutually exclusive" -}}
{{- end -}}
{{- end -}}

{{/*
Build the payload for a chart-managed Secret.

Arguments:
  root: The calling chart's root context.
  targetName: Name of the chart-managed Secret.
  values: Plaintext fallback values rendered through stringData.
  migration: Optional map containing legacyName, annotation, and keyRenames.
  preserveKeys: Optional list restricting which keys persisted data protects.

Persisted target and legacy values are base64-encoded Kubernetes Secret data.
Values are only used for keys absent from persisted data.

Omitting preserveKeys protects every persisted key, which is correct for a
Secret holding only generated credentials. Supplying it protects exactly the
listed keys and lets every other key in values track the chart values, which is
what a Secret mixing credentials with plain configuration needs.
*/}}
{{- define "helx-common.secret.payload.v1" -}}
{{- $root := required "helx-common: secret root context is required" .root -}}
{{- $targetName := required "helx-common: secret targetName is required" .targetName -}}
{{- $migration := default (dict) .migration -}}
{{- $legacyName := default "" (get $migration "legacyName") -}}
{{- $migrationAnnotation := default "secrets.helxplatform.io/migrated-from" (get $migration "annotation") -}}
{{- $keyRenames := default (dict) (get $migration "keyRenames") -}}

{{/* Fresh installs are deterministic with respect to the cluster. */}}
{{- $targetSecret := dict -}}
{{- $legacySecret := dict -}}
{{- if $root.Release.IsUpgrade -}}
  {{- $targetSecret = lookup "v1" "Secret" $root.Release.Namespace $targetName -}}
  {{- if and $legacyName (ne $legacyName $targetName) -}}
    {{- $legacySecret = lookup "v1" "Secret" $root.Release.Namespace $legacyName -}}
  {{- end -}}
{{- end -}}

{{/* Copy each source because key normalization mutates its map. */}}
{{- $targetData := deepCopy (default (dict) $targetSecret.data) -}}
{{- $legacyData := deepCopy (default (dict) $legacySecret.data) -}}
{{- $valuesData := dict -}}
{{- range $key, $value := (default (dict) .values) -}}
  {{- $_ := set $valuesData $key (toString $value) -}}
{{- end -}}

{{/* Normalize each source independently so merge precedence remains correct. */}}
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
  {{/* The annotated target is canonical; legacy data only fills gaps. */}}
  {{- $_ := set $annotations $migrationAnnotation (get $existingAnnotations $migrationAnnotation) -}}
  {{- $data = mergeOverwrite (dict) $legacyData $targetData -}}
{{- else if $legacySecret -}}
  {{/* First migration: normalized legacy data is canonical. */}}
  {{- $_ := set $annotations $migrationAnnotation $legacyName -}}
  {{- $data = mergeOverwrite (dict) $targetData $legacyData -}}
{{- else -}}
  {{- $data = $targetData -}}
{{- end -}}

{{/* Keys outside preserveKeys follow values instead of persisted data. */}}
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
Render the resources for one three-mode Secret contract.

Arguments:
  root: Calling chart's root context.
  defaultName: Name used by chart-managed mode and as the default ESO target.
  existingSecret: Optional caller-managed Secret name.
  values: Plaintext chart-managed fallback values.
  externalSecret: ESO settings (enabled, refreshInterval, secretStoreRef, remoteRef).
  externalSecretName: Optional ExternalSecret resource name; defaults to defaultName.
  migration: Optional migration settings accepted by secret.payload.v1.
  preserveKeys: Optional list passed through to secret.payload.v1.
  requiredKeys: Optional list of non-empty keys required in the final managed payload.
  type: Optional Kubernetes Secret type; defaults to Opaque.
  retain: Optional boolean; defaults to true.

The chart-managed Secret carries helm.sh/resource-policy: keep so that handing
ownership to existingSecret or ESO under the same Secret name does not delete
the live credentials when the resource leaves the rendered manifest. Helm reads
that annotation from the live object, so the annotation must already have been
applied by an earlier upgrade: upgrade to a chart carrying this helper first,
then change ownership in a separate upgrade. Set retain to false only for a
Secret whose contents are fully reproducible from values.
*/}}
{{- define "helx-common.secret.resources.v1" -}}
{{- $root := required "helx-common: secret root context is required" .root -}}
{{- $defaultName := required "helx-common: secret defaultName is required" .defaultName -}}
{{- $existingSecret := default "" .existingSecret -}}
{{- $externalSecret := default (dict) .externalSecret -}}
{{- $externalEnabled := default false (get $externalSecret "enabled") -}}
{{- $externalTargetName := default $defaultName (get $externalSecret "targetName") -}}
{{- $secretType := default "Opaque" (get . "type") -}}
{{- $retain := true -}}
{{- if hasKey . "retain" -}}
  {{- $retain = .retain -}}
{{- end -}}
{{- include "helx-common.secret.validate.v1" (dict "existingSecret" $existingSecret "externalSecret" $externalSecret) -}}

{{- if and (not $existingSecret) (not $externalEnabled) -}}
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

{{- if $externalEnabled }}
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

{{/* Retain a distinct legacy Secret while a Helm migration is in progress. */}}
{{- $migration := default (dict) .migration -}}
{{- $legacyName := default "" (get $migration "legacyName") -}}
{{- if and (not $existingSecret) (not $externalEnabled) $root.Release.IsUpgrade $legacyName (ne $legacyName $defaultName) -}}
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
