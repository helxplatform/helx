{{/*
Expand the name of the chart.
*/}}
{{- define "resty.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "resty.fullname" -}}
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
{{- define "resty.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "resty.labels" -}}
helm.sh/chart: {{ include "resty.chart" . }}
{{ include "resty.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "resty.selectorLabels" -}}
app.kubernetes.io/name: {{ include "resty.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Preserve the legacy chart-managed basic-auth Secret name across upgrades.
*/}}
{{- define "resty.basicAuthManagedSecretName" -}}
{{- printf "%s-nginx-htpasswd" .Release.Name -}}
{{- end }}

{{/*
Resolve the basic-auth Secret selected by managed, existingSecret, or ESO mode.
*/}}
{{- define "resty.basicAuthSecretName" -}}
{{- include "helx-common.secret.name.v1" (dict
  "defaultName" (include "resty.basicAuthManagedSecretName" .)
  "existingSecret" .Values.secret.existingSecret
  "externalSecret" .Values.secret.externalSecret
) -}}
{{- end }}

{{/*
Resolve the values used for the chart-managed basic-auth Secret.

`secret.values.auth` carries a precomputed htpasswd entry. `basicAuth.username`
and `basicAuth.password` are the pre-2.0 spelling and still work: the entry is
derived from them when `secret.values.auth` is unset. Deriving re-hashes on every
render because bcrypt salts are random, so the Secret is rewritten on each
upgrade, exactly as it was before; set `secret.values.auth` to pin it.
*/}}
{{- define "resty.basicAuthSecretValues" -}}
{{- $values := deepCopy (default (dict) .Values.secret.values) -}}
{{- $username := default "" .Values.basicAuth.username -}}
{{- $password := default "" .Values.basicAuth.password -}}
{{- if or $username $password -}}
  {{- if not (and $username $password) -}}
    {{- fail "resty: basicAuth.username and basicAuth.password must be set together" -}}
  {{- end -}}
  {{- if get $values "auth" -}}
    {{- fail "resty: set either secret.values.auth or basicAuth.username/password, not both" -}}
  {{- end -}}
  {{- if or .Values.secret.existingSecret (default false .Values.secret.externalSecret.enabled) -}}
    {{- fail "resty: basicAuth.username/password only populate the chart-managed Secret; clear them when using secret.existingSecret or secret.externalSecret" -}}
  {{- end -}}
  {{- $_ := set $values "auth" (htpasswd $username $password) -}}
{{- end -}}
{{- toYaml $values -}}
{{- end }}
