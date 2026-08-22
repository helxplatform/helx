# helx-ldap

![Version: 0.1.5](https://img.shields.io/badge/Version-0.1.5-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 2.6.9](https://img.shields.io/badge/AppVersion-2.6.9-informational?style=flat-square)

HeLx LDAP deployment and configuration

## Requirements

| Repository | Name | Version |
|------------|------|---------|
| https://jp-gouin.github.io/helm-openldap/ | openldap(openldap-stack-ha) | 4.3.3 |
| oci://ghcr.io/helxplatform/helm-charts | helx-common | 0.1.0 |

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| configuration.adminDN | string | `""` |  |
| configuration.anonymousAccess.enabled | bool | `true` |  |
| configuration.baseDN | string | `""` |  |
| configuration.configDN | string | `"cn=admin,cn=config"` |  |
| configuration.enabled | bool | `true` |  |
| configuration.image.pullPolicy | string | `""` |  |
| configuration.image.repository | string | `""` |  |
| configuration.image.tag | string | `""` |  |
| configuration.job.activeDeadlineSeconds | int | `300` |  |
| configuration.job.backoffLimit | int | `6` |  |
| configuration.job.podSecurityContext.fsGroup | int | `1001` |  |
| configuration.job.podSecurityContext.seccompProfile.type | string | `"RuntimeDefault"` |  |
| configuration.job.securityContext.allowPrivilegeEscalation | bool | `false` |  |
| configuration.job.securityContext.capabilities.drop[0] | string | `"ALL"` |  |
| configuration.job.securityContext.runAsGroup | int | `1001` |  |
| configuration.job.securityContext.runAsNonRoot | bool | `true` |  |
| configuration.job.securityContext.runAsUser | int | `1001` |  |
| configuration.job.securityContext.seccompProfile.type | string | `"RuntimeDefault"` |  |
| configuration.job.ttlSecondsAfterFinished | int | `300` |  |
| configuration.memberofModulePath | string | `"/opt/bitnami/openldap/lib/openldap/memberof.so"` |  |
| configuration.serviceName | string | `""` |  |
| openldap.env.LDAP_ALLOW_ANON_BINDING | string | `"yes"` |  |
| openldap.fullnameOverride | string | `"openldap"` |  |
| openldap.global.existingSecret | string | `"openldap-credentials"` | Secret name consumed by the upstream OpenLDAP chart. This is target-name compatibility plumbing for the dependency, not a fourth ownership mode. It must match secret.existingSecret or secret.externalSecret.targetName when either is set. Chart-managed and default ESO modes create this name. |
| openldap.global.ldapDomain | string | `"example.org"` |  |
| openldap.ltb-passwd.enabled | bool | `false` |  |
| openldap.migration.enabled | bool | `false` | Enable one-time migration of an existing HeLx LDAP PVC during a Helm upgrade. |
| openldap.migration.image.pullPolicy | string | `IfNotPresent` | Image pull policy for the migration hook. |
| openldap.migration.image.repository | string | `registry.k8s.io/kubectl` | Image containing kubectl and /bin/sh for the migration hook. |
| openldap.migration.image.tag | string | `v1.31.0` | Migration hook image tag. |
| openldap.migration.job.activeDeadlineSeconds | int | `600` | Maximum runtime for the migration hook Job. |
| openldap.migration.job.backoffLimit | int | `0` | Number of retries for the migration hook Job. |
| openldap.migration.legacyPvc | string | `""` | PVC to adopt; must match openldap.persistence.existingClaim during migration. |
| openldap.migration.legacyStatefulSet | string | `""` | Optional prior HeLx LDAP StatefulSet name; otherwise labels are used for discovery. |
| openldap.persistence.enabled | bool | `true` |  |
| openldap.persistence.existingClaim | string | `""` | Existing PVC to mount instead of creating a StatefulSet volumeClaimTemplate. Keep set after adoption. |
| openldap.phpldapadmin.enabled | bool | `false` |  |
| openldap.replicaCount | int | `1` |  |
| openldap.replication.enabled | bool | `false` |  |
| openldap.resources.limits.cpu | string | `"1"` |  |
| openldap.resources.limits.memory | string | `"500M"` |  |
| openldap.resources.requests.cpu | string | `"500m"` |  |
| openldap.resources.requests.memory | string | `"500M"` |  |
| openldap.test.enabled | bool | `false` |  |
| secret.existingSecret | string | `""` | Name of a caller-managed HeLx LDAP credentials Secret containing LDAP_ADMIN_PASSWORD and LDAP_CONFIG_ADMIN_PASSWORD. Most prior deployments will have an existing Secret named "openldap-credentials". Set this to that value for a seamless upgrade, and do not set the secret values in the values section below. |
| secret.externalSecret | object | `{"enabled":false,"refreshInterval":"1h","remoteRef":"","secretStoreRef":{"kind":"SecretStore","name":"vault"},"targetName":""}` | Configure an ExternalSecret to populate the HeLx LDAP credentials Secret. This is mutually exclusive with secret.existingSecret. |
| secret.externalSecret.targetName | string | `""` | Optional ESO target Secret name. Defaults to openldap.global.existingSecret. |
| secret.migration.enabled | bool | `false` | Enable one-time credentials Secret migration during a Helm upgrade. |
| secret.migration.legacySecret | string | `""` | Previous HeLx LDAP credentials Secret name; it is copied and not deleted automatically. |
| secret.values | object | `{}` | Key/value pairs used to create the chart-managed HeLx LDAP credentials Secret when secret.existingSecret is empty and externalSecret is disabled. Required keys:   LDAP_ADMIN_PASSWORD: password for the HeLx LDAP directory administrator   LDAP_CONFIG_ADMIN_PASSWORD: password for the cn=config administrator Argo CD users should provide stable encrypted values or select ESO mode. |

## Existing release migration

The upstream chart creates a StatefulSet named `openldap` and, with the default
settings, a PVC named `data-openldap-0`. A fresh upgrade that changes the
StatefulSet from its `volumeClaimTemplates` to an explicit PVC can fail because
that StatefulSet field is immutable. Use the migration values only after
verifying the live object names and backing up the HeLx LDAP data:

```yaml
helx-ldap:
  openldap:
    migration:
      enabled: true
      legacyPvc: "data-legacy-statefulset-0"
      # Set this only when label discovery is ambiguous or unavailable.
      legacyStatefulSet: ""
    persistence:
      existingClaim: "data-legacy-statefulset-0"
  secret:
    existingSecret: openldap-credentials
    migration:
      enabled: true
      legacySecret: "legacy-credentials-secret"
```

`legacyPvc` and `persistence.existingClaim` must be the same existing claim.
The Secret migration is optional when the old credentials Secret is already
`openldap-credentials`; otherwise the pre-upgrade hook copies the old Secret's
keys into that target. It requires a live `helm upgrade`, preserves the target
as caller-managed, and does not delete the old Secret.

The pre-upgrade migration hook performs the handoff automatically: it scales the
prior HeLx LDAP StatefulSet to zero, waits for its pods to terminate, and deletes
only the old StatefulSet controller with orphan propagation. The PVC and backing
volume are retained, so no manual scale-down or StatefulSet deletion is required.
Do not run two StatefulSets against an RWO claim. After the upgrade, disable both
migration flags but keep `openldap.persistence.existingClaim` set permanently.

Verify the result with `kubectl`: the StatefulSet should mount the adopted claim
through `spec.template.spec.volumes[].persistentVolumeClaim.claimName`, and its
PVC UID should be unchanged. The migration hooks use `lookup`, so client-side
`helm template` and Argo CD rendering cannot validate or perform the Secret
copy.

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)
