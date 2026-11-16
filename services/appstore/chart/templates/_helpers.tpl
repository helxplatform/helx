{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "appstore.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "appstore.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Name of the chart's Service: the bare chart name, not "<release>-<chart>",
so other components can address it at a fixed name. fullnameOverride still
takes over, which lets two releases share a namespace.
*/}}
{{- define "appstore.serviceName" -}}
{{- default .Chart.Name .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "appstore.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "appstore.labels" -}}
helm.sh/chart: {{ include "appstore.chart" . }}
{{ include "appstore.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "appstore.selectorLabels" -}}
app.kubernetes.io/name: {{ include "appstore.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Create the name of the service account to use
*/}}
{{- define "appstore.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
    {{ default (include "appstore.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
    {{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}

{{/*
Name of the chart-managed appstore Secret. Reserve space before adding the
suffix so the result remains a valid Kubernetes resource name.
*/}}
{{- define "appstore.managedSecretName" -}}
{{- printf "%s-secrets" (include "appstore.fullname" . | trunc 55 | trimSuffix "-") -}}
{{- end -}}

{{/*
Name of the Secret consumed by the appstore Deployment.
*/}}
{{- define "appstore.secretName" -}}
{{- include "helx-common.secret.name.v1" (dict
  "mode" .Values.secret.mode
  "secretValueBlockPath" "secret"
  "defaultName" (include "appstore.managedSecretName" .)
  "existingSecret" .Values.secret.existingSecret
  "externalSecret" .Values.secret.externalSecret
) -}}
{{- end -}}

{{/*
Print a numeric ID as an integer. Helm reads numbers in values files as
float64, which print in scientific notation from 1e6 up, so 1002160002 would
become 1.002160002e+09. Anything that is not a float (unset, a string, an
integer from --set) prints unchanged, because Tycho treats "" and "0"
differently.
*/}}
{{- define "appstore.intValue" -}}
{{- if kindIs "float64" . -}}
{{- int64 . -}}
{{- else -}}
{{- . -}}
{{- end -}}
{{- end -}}

{{/*
Name of the primary Secret created by the legacy chart.
*/}}
{{- define "appstore.legacySecretName" -}}
{{- include "appstore.fullname" . -}}
{{- end -}}
