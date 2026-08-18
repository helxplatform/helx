# image-utils

Tools to help with help with management of images in the cluster.

![Version: 2.0.0](https://img.shields.io/badge/Version-2.0.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.0.0](https://img.shields.io/badge/AppVersion-1.0.0-informational?style=flat-square)

The imagepullsecret-patcher resources are maintained by this parent chart and are
created when `imagepullsecret-patcher.enabled` is true. The source registry
credential uses the standard three-mode `secret` block provided by `helx-common`:
a chart-managed Secret, a caller-managed `existingSecret`, or an ESO-managed
Secret. The source Secret must contain `.dockerconfigjson` and has type
`kubernetes.io/dockerconfigjson` when managed by this chart or ESO.

The default source Secret target is `image-pull-secret`. The whole Secret is
mounted at `/app/secrets`, allowing Kubernetes and ESO updates to refresh the
projected `.dockerconfigjson` file. Its path is passed through
`imagepullsecret-patcher.config.dockerconfigjsonpath`; credential JSON is not
placed in an environment variable. `imagepullsecret-patcher.config.secretname`
is the separate destination Secret name propagated to namespaces. No legacy
Secret migration is performed.

The former plaintext `imageCredentials` and
`imagepullsecret-patcher.config.dockerconfigjson` settings are not supported.
Provide source credentials through `secret.values[".dockerconfigjson"]`,
`secret.existingSecret`, or `secret.externalSecret`.

A cluster-aware Helm upgrade preserves data from the historical
`image-pull-secret` because the managed target name is unchanged. Argo CD cannot
rely on Helm `lookup`; when adopting Argo CD for an existing release, select
`secret.existingSecret: image-pull-secret` or move the credential to ESO/Vault
before syncing this chart.

Original patcher code: https://github.com/titansoft-pte-ltd/imagepullsecret-patcher.

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| https://helxplatform.github.io/helm-charts | kubernetes-image-puller | 1.0.0 |
| oci://ghcr.io/helxplatform/helm-charts | helx-common | 0.1.0 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| imagepullsecret-patcher.affinity | object | `{}` |  |
| imagepullsecret-patcher.config.allserviceaccount | bool | `false` | List and patch all service accounts, ignoring serviceaccounts. |
| imagepullsecret-patcher.config.debug | bool | `false` | Show DEBUG logs. |
| imagepullsecret-patcher.config.dockerconfigjsonpath | string | `"/app/secrets/.dockerconfigjson"` | Path at which the selected source Secret's .dockerconfigjson key is mounted. This is passed to CONFIG_DOCKERCONFIGJSONPATH. |
| imagepullsecret-patcher.config.excludednamespaces | string | `""` | Comma-separated namespaces excluded from processing. |
| imagepullsecret-patcher.config.force | bool | `true` | Overwrite destination secrets when they do not match. |
| imagepullsecret-patcher.config.loopduration | string | `"10s"` | How often namespaces are checked, as a Go duration string. |
| imagepullsecret-patcher.config.managedonly | bool | `false` | Only modify secrets created by imagepullsecret-patcher. |
| imagepullsecret-patcher.config.runonce | bool | `false` | Run the update loop once, allowing for external scheduling. |
| imagepullsecret-patcher.config.secretname | string | `"image-pull-secret"` | Destination Secret name propagated to namespaces. This is independent of the source Secret selected through the top-level secret block. |
| imagepullsecret-patcher.config.serviceaccounts | string | `"default"` | Comma-separated list of service accounts to patch. |
| imagepullsecret-patcher.enabled | bool | `false` |  |
| imagepullsecret-patcher.fullnameOverride | string | `""` |  |
| imagepullsecret-patcher.image.pullPolicy | string | `"IfNotPresent"` |  |
| imagepullsecret-patcher.image.repository | string | `"helxplatform/imagepullsecret-patcher"` |  |
| imagepullsecret-patcher.image.tag | string | `"0.0.15"` | Overrides the patcher's historical app version. |
| imagepullsecret-patcher.imagePullSecrets | list | `[]` |  |
| imagepullsecret-patcher.nameOverride | string | `""` |  |
| imagepullsecret-patcher.nodeSelector | object | `{}` |  |
| imagepullsecret-patcher.podAnnotations | object | `{}` |  |
| imagepullsecret-patcher.podSecurityContext | object | `{}` |  |
| imagepullsecret-patcher.replicaCount | int | `1` |  |
| imagepullsecret-patcher.resources.limits.cpu | float | `0.2` |  |
| imagepullsecret-patcher.resources.limits.memory | string | `"30Mi"` |  |
| imagepullsecret-patcher.resources.requests.cpu | float | `0.1` |  |
| imagepullsecret-patcher.resources.requests.memory | string | `"15Mi"` |  |
| imagepullsecret-patcher.securityContext | object | `{}` |  |
| imagepullsecret-patcher.serviceAccount.annotations | object | `{}` | Annotations to add to the service account. |
| imagepullsecret-patcher.serviceAccount.create | bool | `true` | Specifies whether a service account should be created. |
| imagepullsecret-patcher.serviceAccount.name | string | `""` | Service account name. Generated from the release name when empty and create is true; defaults to default when create is false. |
| imagepullsecret-patcher.tolerations | list | `[]` |  |
| kubernetes-image-puller.enabled | bool | `false` |  |
| secret.existingSecret | string | `""` | Name of a caller-managed source registry credential Secret containing .dockerconfigjson. When set, the chart does not create or manage a Secret. |
| secret.externalSecret | object | `{"enabled":false,"refreshInterval":"1h","remoteRef":"","secretStoreRef":{"kind":"SecretStore","name":"vault"},"targetName":""}` | Configure an ExternalSecret to populate the source registry credential Secret. This is mutually exclusive with secret.existingSecret. |
| secret.externalSecret.targetName | string | `""` | Optional ESO target Secret name. Defaults to image-pull-secret. |
| secret.values | object | `{}` | Key/value pairs used to create the chart-managed source registry credential Secret when existingSecret is empty and externalSecret is disabled. Required key: .dockerconfigjson. The value must be a Docker config JSON document. Prefer encrypted values, ESO, or existingSecret in production. |

Namespaces can opt out by setting the
`k8s.titansoft.com/imagepullsecret-patcher-exclude: "true"` annotation.

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
