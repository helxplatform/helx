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
Build the application Secret alias-to-resource-name map consumed by config.json
and the Deployment's volumes. Known aliases are reserved so additional
caller-managed entries cannot silently replace them.

config.secrets was removed in chart 2.0.0. It is deliberately absent from
values.yaml, so hasKey detects a caller-supplied map and fails rather than
ignoring it: silently dropping a custom Secret name would leave the webhook
serving a certificate the caller never chose. Point secret.existingSecret and
ldap.secret.existingSecret at those Secrets instead.
*/}}
{{- define "user-mutator.effectiveSecretNames" -}}
{{- if hasKey .Values.config "secrets" -}}
  {{- fail "user-mutator: config.secrets was removed in chart 2.0.0; move its cert entry to secret.existingSecret, its ldap-password entry to ldap.secret.existingSecret, and any other entry to config.additionalSecrets" -}}
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
Validate that exactly one webhook TLS ownership mode is selected. generate is a
fourth mode alongside the three helx-common contracts, so it has to be checked
here rather than by the library.
*/}}
{{- define "user-mutator.validateTlsMode" -}}
{{- if .Values.secret.generate.enabled -}}
  {{- if .Values.secret.existingSecret -}}
    {{- fail "user-mutator: secret.generate.enabled and secret.existingSecret are mutually exclusive; set secret.existingSecret to \"\" to let the chart generate the webhook certificate" -}}
  {{- end -}}
  {{- if .Values.secret.externalSecret.enabled -}}
    {{- fail "user-mutator: secret.generate.enabled and secret.externalSecret.enabled are mutually exclusive" -}}
  {{- end -}}
  {{- if .Values.secret.values -}}
    {{- fail "user-mutator: secret.generate.enabled ignores secret.values; clear one of them" -}}
  {{- end -}}
{{- end -}}
{{- include "user-mutator.validateSecretValuesUnused" (dict
  "label" "secret"
  "existingSecret" .Values.secret.existingSecret
  "externalSecretEnabled" .Values.secret.externalSecret.enabled
  "values" .Values.secret.values
) -}}
{{- include "user-mutator.validateSecretValuesUnused" (dict
  "label" "ldap.secret"
  "existingSecret" .Values.ldap.secret.existingSecret
  "externalSecretEnabled" .Values.ldap.secret.externalSecret.enabled
  "values" .Values.ldap.secret.values
) -}}
{{- end -}}

{{/*
Reject a values block that cannot take effect. helx-common renders the
chart-managed Secret only when neither existingSecret nor externalSecret is
selected, so values supplied alongside either is silently dropped, and the
caller is left believing they configured a Secret the chart never writes. This
chart passes both values blocks through verbatim, so the check is exact; a
chart that folds unrelated configuration into its values dict would need a
narrower rule.
*/}}
{{- define "user-mutator.validateSecretValuesUnused" -}}
{{- if .values -}}
  {{- if .existingSecret -}}
    {{- fail (printf "user-mutator: %s.values is ignored when %s.existingSecret is set (%q owns the Secret); clear one of them" .label .label .existingSecret) -}}
  {{- end -}}
  {{- if .externalSecretEnabled -}}
    {{- fail (printf "user-mutator: %s.values is ignored when %s.externalSecret.enabled is true (External Secrets owns the Secret); clear one of them" .label .label) -}}
  {{- end -}}
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

{{/*
Guard webhook.caBundle's encoding. The field is substituted into the
MutatingWebhookConfiguration verbatim and Kubernetes expects base64 there,
while every place an operator copies a CA from holds PEM, so pasting raw PEM is
the likely mistake. Both failures are silent at runtime: the API server cannot
verify the serving certificate, and webhook.failurePolicy defaults to Ignore.

Takes the bundle string as its context, not the root.
*/}}
{{- define "user-mutator.validateCaBundle" -}}
{{- $caBundle := . -}}
{{- if $caBundle -}}
  {{- if hasPrefix "-----BEGIN" $caBundle -}}
    {{- fail "user-mutator: webhook.caBundle is raw PEM and has to be base64-encoded. Encode it with: base64 < ca.crt | tr -d '\n'" -}}
  {{- end -}}
  {{- if not (hasPrefix "-----BEGIN" (b64dec $caBundle)) -}}
    {{- fail "user-mutator: webhook.caBundle does not decode to a PEM certificate. It must be the base64 of a PEM CA certificate; a doubly-encoded or truncated value fails the TLS handshake silently because webhook.failurePolicy defaults to Ignore." -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{/*
Explain how to supply the CA bundle, naming only the options that apply to the
ownership mode actually selected and where to read the value from.
*/}}
{{- define "user-mutator.missingCaBundleMessage" -}}
{{- $lines := list "user-mutator: webhook.enabled needs the CA that signed the webhook serving certificate, and none is available." -}}
{{- if .Values.secret.existingSecret -}}
  {{- $lines = append $lines (printf "secret.existingSecret is %q, and the chart never reads a caller-managed Secret at render time, so supply the CA yourself:" .Values.secret.existingSecret) -}}
  {{- $lines = append $lines (printf "  webhook.caBundle=$(kubectl -n %s get secret %s -o jsonpath='{.data.ca\\.crt}')" .Release.Namespace .Values.secret.existingSecret) -}}
  {{- $lines = append $lines "If that Secret has no ca.crt, the CA is whatever signed its tls.crt; for a self-signed certificate tls.crt is its own CA:" -}}
  {{- $lines = append $lines (printf "  webhook.caBundle=$(kubectl -n %s get secret %s -o jsonpath='{.data.tls\\.crt}')" .Release.Namespace .Values.secret.existingSecret) -}}
{{- else if .Values.secret.externalSecret.enabled -}}
  {{- $lines = append $lines "secret.externalSecret is enabled, and the chart cannot read an ESO-populated Secret at render time, so supply the CA yourself:" -}}
  {{- $lines = append $lines (printf "  webhook.caBundle=$(kubectl -n %s get secret %s -o jsonpath='{.data.ca\\.crt}')" .Release.Namespace (include "user-mutator.tlsManagedSecretName" .)) -}}
  {{- $lines = append $lines "That requires the ExternalSecret to have synced at least once." -}}
{{- else -}}
  {{- $lines = append $lines "In values mode the chart writes the Secret from secret.values but does not read the CA back out of it, so name it once here:" -}}
  {{- $lines = append $lines "  webhook.caBundle=$(base64 < ca.crt | tr -d '\\n')" -}}
  {{- $lines = append $lines "For a self-signed certificate the CA is tls.crt itself." -}}
{{- end -}}
{{- $lines = append $lines "Or set secret.generate.enabled=true to have the chart generate and manage the certificate, or webhook.enabled=false to manage the MutatingWebhookConfiguration yourself." -}}
{{- join "\n" $lines -}}
{{- end -}}
