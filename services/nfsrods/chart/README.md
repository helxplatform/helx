# nfsrods

A standalone NFSv4.1 server (via nfs4j) with a Virtual File System implementation supporting the iRODS Data Management Platform.

![Version: 3.0.0](https://img.shields.io/badge/Version-3.0.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 2.1.0](https://img.shields.io/badge/AppVersion-2.1.0-informational?style=flat-square)

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| oci://ghcr.io/helxplatform/helm-charts | helx-common | 0.1.0 |

`nfsrods` works by creating a fake PersistentVolume which acts as a pointer to the `nfsrods` Service IP. When a pod mounts the `nfsrods` PersistentVolume, kubelet will send NFS commands to the service IP listed in the PersistentVolume. Since Helm ensures the `service.ip` is the same in the Service and the PersistentVolume, the NFS traffic can flow as if talking to any other external NFS server.

NOTE: The PersistentVolume and Claim are set be retained if the helm chart is uninstalled. This allows for non-cluster-admins to re-deploy since they do not have the permission to create and delete PersistentVolumes.

## Proxy-admin credentials

The final `server.json` requires these Secret keys:

- `IRODS_PROXY_ADMIN_USERNAME`
- `IRODS_PROXY_ADMIN_PASSWORD`

Configure exactly one of the helx-common ownership modes:

1. Leave `secret.existingSecret` empty and `secret.externalSecret.enabled` false, then provide both keys through `secret.values` for a chart-managed Secret.
2. Set `secret.existingSecret` to a caller-managed Secret containing both keys.
3. Enable `secret.externalSecret` and configure its backend reference so External Secrets Operator creates a Secret containing both keys.

No legacy Secret migration is performed. The ConfigMap contains only the nonsecret base `server.json`. A Python init container reads that base and the selected Secret, inserts `proxy_admin_account`, and writes the completed file to an `emptyDir` mounted by the main container. `exports` and `log4j.properties` remain mounted directly from the ConfigMap.

Because the credentials are assembled by an init container, a running Pod must be restarted after the selected Secret changes. ESO users can configure their preferred Secret-reloader annotation through `podAnnotations`, or perform a rollout as part of credential rotation.

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| affinity | object | `{}` |  |
| fullnameOverride | string | `""` |  |
| global.stdnfsPvc | string | `"stdnfs"` |  |
| image.pullPolicy | string | `"IfNotPresent"` |  |
| image.repository | string | `"irods/nfsrods"` |  |
| imagePullSecrets | list | `[]` |  |
| nameOverride | string | `""` |  |
| nodeSelector | object | `{}` |  |
| podAnnotations | object | `{}` | Additional annotations for the nfsrods Pod. A Secret-reloader annotation can be supplied here when automatic restarts after ESO rotation are required. |
| podSecurityContext | object | `{}` |  |
| replicaCount | int | `1` |  |
| resources.limits.cpu | string | `"500m"` |  |
| resources.limits.memory | string | `"1Gi"` |  |
| resources.requests.cpu | string | `"100m"` |  |
| resources.requests.memory | string | `"128Mi"` |  |
| runArgs | string | `"/usr/sbin/useradd -m -u 1000 -s /bin/bash rods; ./start.sh"` |  |
| secret.existingSecret | string | `""` | Name of a caller-managed Secret containing IRODS_PROXY_ADMIN_USERNAME and IRODS_PROXY_ADMIN_PASSWORD. When set, the chart does not create or manage a Secret. |
| secret.externalSecret | object | `{"enabled":false,"refreshInterval":"1h","remoteRef":"","secretStoreRef":{"kind":"SecretStore","name":"vault"},"targetName":""}` | Configure an ExternalSecret to populate the proxy-admin Secret. This is mutually exclusive with secret.existingSecret. |
| secret.externalSecret.targetName | string | `""` | Optional ESO target Secret name. Defaults to <fullname>-secrets. |
| secret.migration.enabled | bool | `false` | No legacy Secret migration is performed. Existing installations must select one of the three supported ownership modes explicitly. |
| secret.values | object | `{}` | Key/value pairs used to create the chart-managed proxy-admin Secret when secret.existingSecret is empty and secret.externalSecret is disabled. Required keys:   IRODS_PROXY_ADMIN_USERNAME: iRODS proxy administrator username   IRODS_PROXY_ADMIN_PASSWORD: iRODS proxy administrator password Argo CD users should provide stable encrypted values or select an external ownership mode. |
| securityContext | object | `{}` |  |
| server.irods_client.connection_timeout_in_seconds | int | `600` |  |
| server.irods_client.default_resource | string | `"demoResc"` |  |
| server.irods_client.host | string | `"example.com"` |  |
| server.irods_client.port | int | `1247` |  |
| server.irods_client.ssl_negotiation_policy | string | `"CS_NEG_REFUSE"` |  |
| server.irods_client.zone | string | `"ExampleZone"` |  |
| server.nfs_server.allow_overwrite_of_existing_files | bool | `true` |  |
| server.nfs_server.file_information_refresh_time_in_milliseconds | int | `1000` |  |
| server.nfs_server.irods_mount_point | string | `"/ExampleZone"` |  |
| server.nfs_server.list_operation_query_results_refresh_time_in_milliseconds | int | `30000` |  |
| server.nfs_server.object_type_refresh_time_in_milliseconds | int | `300000` |  |
| server.nfs_server.port | int | `2049` |  |
| server.nfs_server.user_access_refresh_time_in_milliseconds | int | `1000` |  |
| server.nfs_server.user_information_refresh_time_in_milliseconds | int | `3600000` |  |
| server.nfs_server.user_permissions_refresh_time_in_milliseconds | int | `300000` |  |
| server.nfs_server.user_type_refresh_time_in_milliseconds | int | `300000` |  |
| server.nfs_server.using_oracle_database | bool | `false` |  |
| serverJsonInit.image.pullPolicy | string | `"IfNotPresent"` |  |
| serverJsonInit.image.repository | string | `"python"` |  |
| serverJsonInit.image.tag | string | `"3.12-alpine"` |  |
| serverJsonInit.securityContext | object | `{}` |  |
| service.ip | string | `nil` | NOTE: This IP must be a valid, unused IP in the cluster's service CIDR.    A hostname or servicename will not resolve b/c of the DNS settings on nodes.  ip: 10.233.58.200 (previous default) |
| service.mountdPort | int | `20048` |  |
| service.nfsPort | int | `2049` |  |
| service.rpcbindPort | int | `111` |  |
| service.type | string | `"ClusterIP"` |  |
| sharedStorage.createPV | bool | `true` |  |
| sharedStorage.createPVC | bool | `true` |  |
| sharedStorage.nfs.path | string | `"/"` |  |
| sharedStorage.storageClass | string | `"nfsrods-sc"` | This storageClass doesn't need to exist in the cluster since the PVC is directly selecting the PV |
| sharedStorage.storageSize | string | `"100Gi"` | No data is actually stored here, just a pointer to the nfsrods service IP. |
| tolerations | list | `[]` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
