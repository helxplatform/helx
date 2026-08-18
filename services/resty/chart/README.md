# resty

![Version: 2.0.0](https://img.shields.io/badge/Version-2.0.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 2.0.1](https://img.shields.io/badge/AppVersion-2.0.1-informational?style=flat-square)

A Helm chart for Kubernetes

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| oci://ghcr.io/helxplatform/helm-charts | helx-common | 0.1.0 |

## Basic authentication Secrets

Set `basicAuth.enabled=true` to enable ingress basic authentication. The selected
Secret must contain an `auth` key whose value is a precomputed htpasswd entry;
this chart no longer accepts a username or password and does not compute the
entry from plaintext credentials.

The chart supports three mutually exclusive ownership modes:

1. **Chart-managed:** leave `secret.existingSecret` empty and
   `secret.externalSecret.enabled=false`, then provide the precomputed entry as
   `secret.values.auth`. The Secret name remains exactly
   `<release>-nginx-htpasswd`. During a cluster-aware Helm upgrade, existing data
   at that name takes precedence so the entry is preserved.
2. **Caller-managed:** set `secret.existingSecret` to the name of a Secret that
   already contains `auth`. The chart creates no Secret resource.
3. **ESO-managed:** set `secret.externalSecret.enabled=true` and configure its
   store and remote reference. ESO populates `targetName`, which defaults to
   `<release>-nginx-htpasswd`.

Managed mode requires a non-empty `auth` value on a fresh install. Because
client-side renderers such as Argo CD cannot use Helm upgrade lookups to recover
cluster data, provide a stable managed value there or use `existingSecret` or
External Secrets.

The Secret configured by `SSL.nginxTLSSecret` is intentionally separate and
caller-managed. TLS certificates have a different lifecycle from basic-auth
credentials, and this chart does not create or rotate the TLS Secret.

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| DEV_PHASE.dev | bool | `false` | Set the DEV_PHASE.dev True, if Appstore/Tycho running locally. Else, set it to False |
| airflow.authenticate | bool | `true` |  |
| basicAuth.enabled | bool | `false` | Enables basic authentication for the site using the selected Secret. |
| external_http_host | bool | `false` | If using an external http proxy host set this to true and specify serverName.  Used for TACC. |
| fullnameOverride | string | `""` |  |
| global.ambassador_service_name | string | `"ambassador"` |  |
| global.dug_search_client_service_name | string | `"dug-search-client"` |  |
| global.dug_web_service_name | string | `"dug-web"` |  |
| global.restartr_api_service_name | string | `"restartr-api-service"` |  |
| image.pullPolicy | string | `"IfNotPresent"` |  |
| image.repository | string | `"bitnami/openresty"` |  |
| image.tag | float | `1.21` | Overrides the image tag whose default is the chart appVersion. |
| imagePullSecrets | list | `[]` |  |
| ingress.admin.annotations | object | `{}` |  |
| ingress.admin.enabled | bool | `false` | Create an additional Ingress to restrict access to /admin routes |
| ingress.annotations | object | `{}` |  |
| ingress.create | bool | `false` | Create an Ingress resource or not. New installations of helx should set this to true to avoid needing to request a static IP. |
| ingress.ingressClassName | string | `nil` | Set to use a specific ingress class other than the default. |
| ingress.tls.enabled | bool | `true` | Values inserted into the TLS block come from SSL.nginxTLSSecret and service.serverName for backward compatibility |
| nameOverride | string | `""` |  |
| replicaCount | int | `1` |  |
| resources.limits.cpu | string | `"100m"` |  |
| resources.limits.memory | string | `"128Mi"` |  |
| resources.requests.cpu | string | `"50m"` |  |
| resources.requests.memory | string | `"32Mi"` |  |
| restartrApi | bool | `false` |  |
| secret.existingSecret | string | `""` | Name of a caller-managed Secret containing a precomputed htpasswd entry under `auth`. When set, the chart does not manage the Secret. |
| secret.externalSecret | object | `{"enabled":false,"refreshInterval":"1h","remoteRef":"","secretStoreRef":{"kind":"SecretStore","name":"vault"},"targetName":""}` | Configure an ExternalSecret to populate a Secret containing the precomputed htpasswd key `auth`. Mutually exclusive with `secret.existingSecret`. |
| secret.externalSecret.targetName | string | `""` | Optional ESO target Secret name. Defaults to `<release>-nginx-htpasswd`. |
| secret.migration.enabled | bool | `false` | No differently named legacy Secret exists; the managed name is preserved. |
| secret.values | object | `{}` | Values for the chart-managed Secret. Must contain a non-empty, precomputed htpasswd entry under `auth`. |
| service.IP | string | `nil` | The static IP for this service, assigned to you by cluster administrators. Ignored if ingress.create=true. |
| service.httpPort | int | `80` |  |
| service.httpTargetPort | int | `8080` |  |
| service.httpsPort | int | `443` |  |
| service.httpsTargetPort | int | `8443` |  |
| service.serverName | string | `"_"` |  |
| service.type | string | `"LoadBalancer"` | can be LoadBalancer or ClusterIP. If ingress.create=true, this setting is ignored and defaulted to ClusterIP |
| stubStatus.enabled | bool | `false` |  |
| stubStatus.localhostOnly | bool | `true` |  |
| stubStatus.stubStatusLocation | string | `"/nginx_status"` |  |
| varStorage.claimName | string | `nil` |  |
| varStorage.existingClaim | bool | `false` |  |
| varStorage.storageClass | string | `nil` |  |
| varStorage.storageSize | string | `"2Gi"` |  |
| workerConnections | int | `1024` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs](https://github.com/norwoodj/helm-docs)
