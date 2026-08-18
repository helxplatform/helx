{{/* Expand the imagepullsecret-patcher component name. */}}
{{- define "image-utils.imagepullsecret-patcher.name" -}}
{{- $patcher := index .Values "imagepullsecret-patcher" -}}
{{- default "imagepullsecret-patcher" $patcher.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Preserve the former subchart's default resource naming. */}}
{{- define "image-utils.imagepullsecret-patcher.fullname" -}}
{{- $patcher := index .Values "imagepullsecret-patcher" -}}
{{- if $patcher.fullnameOverride -}}
{{- $patcher.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "image-utils.imagepullsecret-patcher.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Parent chart name and version for resource labels. */}}
{{- define "image-utils.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Labels for parent-owned imagepullsecret-patcher resources. */}}
{{- define "image-utils.imagepullsecret-patcher.labels" -}}
helm.sh/chart: {{ include "image-utils.chart" . }}
{{ include "image-utils.imagepullsecret-patcher.selectorLabels" . }}
app.kubernetes.io/version: "0.0.15"
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Selector labels retained from the former subchart. */}}
{{- define "image-utils.imagepullsecret-patcher.selectorLabels" -}}
app.kubernetes.io/name: {{ include "image-utils.imagepullsecret-patcher.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Resolve the patcher's service account name. */}}
{{- define "image-utils.imagepullsecret-patcher.serviceAccountName" -}}
{{- $patcher := index .Values "imagepullsecret-patcher" -}}
{{- if $patcher.serviceAccount.create -}}
{{- default (include "image-utils.imagepullsecret-patcher.fullname" .) $patcher.serviceAccount.name -}}
{{- else -}}
{{- default "default" $patcher.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Resolve the source registry credential Secret through helx-common. */}}
{{- define "image-utils.sourceRegistrySecretName" -}}
{{- include "helx-common.secret.name.v1" (dict
  "defaultName" "image-pull-secret"
  "existingSecret" .Values.secret.existingSecret
  "externalSecret" .Values.secret.externalSecret
) -}}
{{- end -}}
