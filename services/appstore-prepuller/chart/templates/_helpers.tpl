{{/*
Expand the name of the chart.
*/}}
{{- define "appstore-prepuller.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fullname: release-name + chart-name, truncated to 63 chars.
*/}}
{{- define "appstore-prepuller.fullname" -}}
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
Common labels
*/}}
{{- define "appstore-prepuller.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "appstore-prepuller.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "appstore-prepuller.selectorLabels" -}}
app.kubernetes.io/name: {{ include "appstore-prepuller.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Name of the DaemonSet the controller will patch.
*/}}
{{- define "appstore-prepuller.daemonsetName" -}}
{{ include "appstore-prepuller.fullname" . }}-puller
{{- end }}

{{/*
Service-account name used by the controller.
*/}}
{{- define "appstore-prepuller.serviceAccountName" -}}
{{ include "appstore-prepuller.fullname" . }}-controller
{{- end }}
