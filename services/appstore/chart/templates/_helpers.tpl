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
  "defaultName" (include "appstore.managedSecretName" .)
  "existingSecret" .Values.secret.existingSecret
  "externalSecret" .Values.secret.externalSecret
) -}}
{{- end -}}

{{/*
Name of the primary Secret created by the legacy chart.
*/}}
{{- define "appstore.legacySecretName" -}}
{{- include "appstore.fullname" . -}}
{{- end -}}
