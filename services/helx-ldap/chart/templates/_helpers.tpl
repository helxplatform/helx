{{/*
Expand the name of the chart.
*/}}
{{- define "helx-ldap.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "helx-ldap.fullname" -}}
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
{{- define "helx-ldap.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels.
*/}}
{{- define "helx-ldap.labels" -}}
helm.sh/chart: {{ include "helx-ldap.chart" . }}
{{ include "helx-ldap.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "helx-ldap.selectorLabels" -}}
app.kubernetes.io/name: {{ include "helx-ldap.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Name resources used by the one-time StatefulSet migration hook.
*/}}
{{- define "helx-ldap.migrationName" -}}
{{- printf "%s-migration" (include "helx-ldap.fullname" . | trunc 52 | trimSuffix "-") | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "helx-ldap.migrationJobName" -}}
{{- printf "%s-statefulset" (include "helx-ldap.migrationName" . | trunc 50 | trimSuffix "-") | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
The canonical Secret name consumed by the upstream OpenLDAP chart. The
upstream dependency requires this value before templates render, so the
three-mode selector is validated against it in secrets.yaml.
*/}}
{{- define "helx-ldap.credentialsSecretTargetName" -}}
{{- required "helx-ldap: openldap.global.existingSecret is required" .Values.openldap.global.existingSecret -}}
{{- end -}}

{{/*
The Secret selected by the wrapper's existing, managed, or ESO mode.
*/}}
{{- define "helx-ldap.credentialsSecret" -}}
{{- include "helx-common.secret.name.v1" (dict
  "defaultName" (include "helx-ldap.credentialsSecretTargetName" .)
  "existingSecret" .Values.secret.existingSecret
  "externalSecret" .Values.secret.externalSecret
) -}}
{{- end -}}

{{/*
Resolve the configured LDAP base DN. The upstream chart accepts either a
DNS-style domain or an explicit DN.
*/}}
{{- define "helx-ldap.baseDN" -}}
{{- $domain := default "example.org" .Values.openldap.global.ldapDomain -}}
{{- if .Values.configuration.baseDN -}}
{{- .Values.configuration.baseDN -}}
{{- else if contains "=" $domain -}}
{{- $domain -}}
{{- else -}}
{{- printf "dc=%s" ($domain | replace "." ",dc=") -}}
{{- end -}}
{{- end }}

{{/*
Resolve the LDAP administrator DN used by the anonymous-access ACL.
*/}}
{{- define "helx-ldap.adminDN" -}}
{{- $baseDN := include "helx-ldap.baseDN" . -}}
{{- $adminUser := default "admin" .Values.openldap.global.adminUser -}}
{{- default (printf "cn=%s,%s" $adminUser $baseDN) .Values.configuration.adminDN -}}
{{- end }}
