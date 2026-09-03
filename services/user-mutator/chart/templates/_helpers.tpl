{{/*
Expand the name of the chart.
*/}}
{{- define "user-mutator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "user-mutator.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "user-mutator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "user-mutator.labels" -}}
helm.sh/chart: {{ include "user-mutator.chart" . }}
{{ include "user-mutator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "user-mutator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "user-mutator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "user-mutator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "user-mutator.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the chart-managed webhook TLS Secret.
*/}}
{{- define "user-mutator.tlsManagedSecretName" -}}
{{- printf "%s-tls" (include "user-mutator.fullname" . | trunc 59 | trimSuffix "-") -}}
{{- end -}}

{{/*
Name of the webhook TLS Secret consumed by the Deployment.
*/}}
{{- define "user-mutator.tlsSecretName" -}}
{{- include "user-mutator.validateTlsMode" . -}}
{{- if eq .Values.secret.mode "generate" -}}
{{- include "user-mutator.tlsManagedSecretName" . -}}
{{- else -}}
{{- include "helx-common.secret.name.v1" (dict
  "mode" .Values.secret.mode
  "secretValueBlockPath" "secret"
  "defaultName" (include "user-mutator.tlsManagedSecretName" .)
  "existingSecret" .Values.secret.existingSecret
  "externalSecret" .Values.secret.externalSecret
) -}}
{{- end -}}
{{- end -}}

{{/*
Name of the chart-managed LDAP password Secret.
*/}}
{{- define "user-mutator.ldapManagedSecretName" -}}
{{- printf "%s-ldap-password" (include "user-mutator.fullname" . | trunc 49 | trimSuffix "-") -}}
{{- end -}}

{{/*
Name of the LDAP password Secret consumed by the Deployment.
*/}}
{{- define "user-mutator.ldapSecretName" -}}
{{- include "helx-common.secret.name.v1" (dict
  "mode" .Values.ldap.secret.mode
  "secretValueBlockPath" "ldap.secret"
  "defaultName" (include "user-mutator.ldapManagedSecretName" .)
  "existingSecret" .Values.ldap.secret.existingSecret
  "externalSecret" .Values.ldap.secret.externalSecret
) -}}
{{- end -}}

{{/*
Build the application Secret alias-to-resource-name map consumed by config.json
and the Deployment's volumes. Known aliases are reserved so additional
caller-managed entries cannot silently replace them.

config.secrets was removed in chart 2.0.0. It is deliberately absent from
values.yaml, so hasKey detects a caller-supplied map and fails rather than
ignoring it: silently dropping a custom Secret name would leave the webhook
serving a certificate the caller never chose. Select existingSecret mode and
point secret.existingSecret or ldap.secret.existingSecret at those Secrets
instead.
*/}}
{{- define "user-mutator.effectiveSecretNames" -}}
{{- if hasKey .Values.config "secrets" -}}
  {{- fail "user-mutator: config.secrets is unsupported; use secret.mode: existingSecret with secret.existingSecret for its cert entry, ldap.secret.mode: existingSecret with ldap.secret.existingSecret for its ldap-password entry, and config.additionalSecrets for other entries" -}}
{{- end -}}
{{- $additionalSecrets := default (dict) .Values.config.additionalSecrets -}}
{{- range $reservedKey := list "cert" "ldap-password" -}}
  {{- if hasKey $additionalSecrets $reservedKey -}}
    {{- fail (printf "user-mutator: config.additionalSecrets cannot override reserved key %q" $reservedKey) -}}
  {{- end -}}
{{- end -}}
{{- $secretNames := dict "cert" (include "user-mutator.tlsSecretName" .) -}}
{{- if .Values.config.features.ldap -}}
  {{- $_ := set $secretNames "ldap-password" (include "user-mutator.ldapSecretName" .) -}}
{{- end -}}
{{- range $key, $secretName := $additionalSecrets -}}
  {{- $_ := set $secretNames $key $secretName -}}
{{- end -}}
{{- toYaml $secretNames -}}
{{- end -}}

{{/*
Name of the cluster-scoped MutatingWebhookConfiguration. It is cluster-scoped,
so the default is qualified by namespace to keep two releases in one cluster
from colliding. Set webhook.name to adopt an existing configuration.
*/}}
{{- define "user-mutator.webhookName" -}}
{{- default (printf "%s-webhook-%s" (include "user-mutator.fullname" .) .Release.Namespace) .Values.webhook.name -}}
{{- end -}}

{{/*
Validate the webhook TLS ownership mode. generate is chart-specific, while the
other modes use the shared helx-common contract.
*/}}
{{- define "user-mutator.validateTlsMode" -}}
{{- $mode := default "" .Values.secret.mode -}}
{{- $modes := list "generate" "values" "existingSecret" "externalSecret" -}}
{{- if not (has $mode $modes) -}}
  {{- fail (printf "user-mutator: secret.mode %q is not a mode; use one of: %s" $mode (join ", " $modes)) -}}
{{- end -}}
{{- if eq $mode "generate" -}}
  {{- if .Values.secret.existingSecret -}}
    {{- fail "user-mutator: secret.mode generate cannot be used with secret.existingSecret" -}}
  {{- end -}}
  {{- if .Values.secret.externalSecret.enabled -}}
    {{- fail "user-mutator: secret.mode generate cannot be used with secret.externalSecret.enabled" -}}
  {{- end -}}
  {{- if .Values.secret.values -}}
    {{- fail "user-mutator: secret.mode generate cannot be used with secret.values" -}}
  {{- end -}}
{{- else -}}
  {{- $ordinaryMode := include "helx-common.secret.mode.v1" (dict
    "mode" $mode
    "existingSecret" .Values.secret.existingSecret
    "externalSecret" .Values.secret.externalSecret
    "secretValueBlockPath" "secret"
  ) -}}
{{- end -}}
{{- end -}}

{{/*
Resolve the webhook certificate material, returning base64-encoded tls.crt,
tls.key, and ca.crt.

Persisted material always wins, so an upgrade never rotates the certificate out
from under a MutatingWebhookConfiguration that already carries the matching CA
bundle. The lookup is unconditional rather than gated on Release.IsUpgrade so
that a Secret retained by helm.sh/resource-policy: keep is reused after a
delete and reinstall.

lookup returns nothing during helm template, helm lint, and client-side dry
runs, so those render freshly generated material. That output is only ever
inspected, never applied, but it does mean rendering the chart twice offline
produces two different certificates.
*/}}
{{- define "user-mutator.webhookCertData" -}}
{{- $secretName := include "user-mutator.tlsManagedSecretName" . -}}
{{- $existing := default (dict) (lookup "v1" "Secret" .Release.Namespace $secretName) -}}
{{- $data := default (dict) (get $existing "data") -}}
{{- $crt := default "" (get $data "tls.crt") -}}
{{- $key := default "" (get $data "tls.key") -}}
{{- $ca := default "" (get $data "ca.crt") -}}
{{- if and $crt $key $ca -}}
  {{- dict "tls.crt" $crt "tls.key" $key "ca.crt" $ca | toYaml -}}
{{- else -}}
  {{- $serviceName := include "user-mutator.fullname" . -}}
  {{- $namespace := .Release.Namespace -}}
  {{- $altNames := list
    $serviceName
    (printf "%s.%s" $serviceName $namespace)
    (printf "%s.%s.svc" $serviceName $namespace)
    (printf "%s.%s.svc.cluster.local" $serviceName $namespace)
  -}}
  {{- $days := int .Values.secret.generate.validityDays -}}
  {{- $generatedCa := genCA (printf "%s-ca" $serviceName) $days -}}
  {{- $generatedCert := genSignedCert $serviceName (list) $altNames $days $generatedCa -}}
  {{- dict
    "tls.crt" ($generatedCert.Cert | b64enc)
    "tls.key" ($generatedCert.Key | b64enc)
    "ca.crt" ($generatedCa.Cert | b64enc)
  | toYaml -}}
{{- end -}}
{{- end -}}
