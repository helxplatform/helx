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
{{- include "helx-common.secret.name.v1" (dict
  "defaultName" (include "user-mutator.tlsManagedSecretName" .)
  "existingSecret" .Values.secret.existingSecret
  "externalSecret" .Values.secret.externalSecret
) -}}
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
  "defaultName" (include "user-mutator.ldapManagedSecretName" .)
  "existingSecret" .Values.ldap.secret.existingSecret
  "externalSecret" .Values.ldap.secret.externalSecret
) -}}
{{- end -}}

{{/*
Historical default names for the known contracts. A contract still carrying its
historical default, with no values and no ExternalSecret, means the caller has
not selected any of the three ownership modes, so a deprecated config.secrets
entry may still supply the name.
*/}}
{{- define "user-mutator.legacyTlsSecretName" -}}user-mutator-cert-tls{{- end -}}
{{- define "user-mutator.legacyLdapSecretName" -}}user-mutator-ldap-password{{- end -}}

{{/*
Report whether a contract is untouched. Arguments: contract, legacyDefault.
Renders "true" when untouched and the empty string otherwise.
*/}}
{{- define "user-mutator.contractUntouched" -}}
{{- $contract := .contract -}}
{{- $externalSecret := default (dict) $contract.externalSecret -}}
{{- if and
  (eq $contract.existingSecret .legacyDefault)
  (empty $contract.values)
  (not (default false (get $externalSecret "enabled")))
-}}true{{- end -}}
{{- end -}}

{{/*
Resolve one known contract's Secret name, honouring a deprecated config.secrets
entry when the caller has not selected a new ownership mode. Arguments:
alias, resolved, legacyNames, legacyPresent, contract, legacyDefault.
*/}}
{{- define "user-mutator.resolveKnownSecretName" -}}
{{- $resolved := .resolved -}}
{{- $legacyNames := .legacyNames -}}
{{- if and .legacyPresent (hasKey $legacyNames .alias) -}}
  {{- $legacyName := get $legacyNames .alias -}}
  {{- $untouched := include "user-mutator.contractUntouched" (dict "contract" .contract "legacyDefault" .legacyDefault) -}}
  {{- if $untouched -}}
    {{- $resolved = $legacyName -}}
  {{- else if ne $legacyName $resolved -}}
    {{- fail (printf "user-mutator: config.secrets.%s is deprecated and conflicts with the new contract, which resolves to %q; remove config.secrets.%s" .alias $resolved .alias) -}}
  {{- end -}}
{{- end -}}
{{- $resolved -}}
{{- end -}}

{{/*
Build the application Secret alias-to-resource-name map. Known contracts are
reserved so additional caller-managed entries cannot silently replace them.

config.secrets is deprecated. It is deliberately absent from values.yaml so that
hasKey distinguishes a caller-supplied map from a chart default, which is what
lets a legacy name win only when no new-style mode has been chosen.
*/}}
{{- define "user-mutator.effectiveSecretNames" -}}
{{- $legacyPresent := hasKey .Values.config "secrets" -}}
{{- $legacyNames := default (dict) (get .Values.config "secrets") -}}
{{- $additionalSecrets := default (dict) .Values.config.additionalSecrets -}}
{{- range $reservedKey := list "cert" "ldap-password" -}}
  {{- if hasKey $additionalSecrets $reservedKey -}}
    {{- fail (printf "user-mutator: config.additionalSecrets cannot override reserved key %q" $reservedKey) -}}
  {{- end -}}
{{- end -}}
{{- $secretNames := dict "cert" (include "user-mutator.resolveKnownSecretName" (dict
  "alias" "cert"
  "resolved" (include "user-mutator.tlsSecretName" .)
  "legacyNames" $legacyNames
  "legacyPresent" $legacyPresent
  "contract" .Values.secret
  "legacyDefault" (include "user-mutator.legacyTlsSecretName" .)
)) -}}
{{- if .Values.config.features.ldap -}}
  {{- $_ := set $secretNames "ldap-password" (include "user-mutator.resolveKnownSecretName" (dict
    "alias" "ldap-password"
    "resolved" (include "user-mutator.ldapSecretName" .)
    "legacyNames" $legacyNames
    "legacyPresent" $legacyPresent
    "contract" .Values.ldap.secret
    "legacyDefault" (include "user-mutator.legacyLdapSecretName" .)
  )) -}}
{{- end -}}
{{/* Unknown deprecated entries behave exactly as config.additionalSecrets. */}}
{{- range $key, $secretName := $legacyNames -}}
  {{- if not (has $key (list "cert" "ldap-password")) -}}
    {{- $_ := set $secretNames $key $secretName -}}
  {{- end -}}
{{- end -}}
{{- range $key, $secretName := $additionalSecrets -}}
  {{- $_ := set $secretNames $key $secretName -}}
{{- end -}}
{{- toYaml $secretNames -}}
{{- end -}}
