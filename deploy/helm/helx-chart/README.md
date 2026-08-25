# helx

A Helm chart for deploying HeLx to Kubernetes.

![Version: 4.6.2](https://img.shields.io/badge/Version-4.6.2-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 3.6.4](https://img.shields.io/badge/AppVersion-3.6.4-informational?style=flat-square)

HeLx puts the most advanced analytical scientific models at investigator’s finger tips using equally advanced cloud native, container orchestrated, distributed computing systems. HeLx can be applied in many domains. Its ability to empower researchers to leverage advanced analytical tools without installation or other infrastructure concerns has broad reaching benefits.

```
# Install the published chart from GHCR.
NAMESPACE=helx
helm registry login ghcr.io
helm -n $NAMESPACE --create-namespace install helx \
  oci://ghcr.io/helxplatform/helm-charts/helx --version 4.6.2

# Deploy to a non-GKE cluster.
helm -n $NAMESPACE --create-namespace install helx \
  oci://ghcr.io/helxplatform/helm-charts/helx --version 4.6.2 \
  --set appstore.userStorage.createPVC=true,nfs-server.enabled=false

# Review the output of the Helm install command.  To review the output use the
# status option.
helm -n $NAMESPACE status helx
# Delete the HeLx chart.
helm -n $NAMESPACE delete helx
# Get the default values yaml for HeLx and subcharts.
helm inspect values helx-charts/[helx ambassador nginx etc.]

```

To do more than the most basic install you should create a values.yaml that contains settings for your local HeLx environment.  A sample is below.

```
appstore:
  django:
    APPSTORE_DJANGO_PASSWORD: "< my secret password >"
    AUTHORIZED_USERS: "user1@example.com,user2@example.com,user3@example.com"
  ACCOUNT_DEFAULT_HTTP_PROTOCOL: https
  userStorage:
    createPVC: true
  oauth:
    OAUTH_PROVIDERS: "google,github"
    GOOGLE_NAME: "< secret >"
    GOOGLE_CLIENT_ID: "< secret >"
    GOOGLE_SECRET: "< secret >"
    GITHUB_NAME: "< secret >"
    GITHUB_CLIENT_ID: "< secret >"
    GITHUB_SECRET: "< secret >"

resty:
  service:
    serverName: helx.example.com
  ingress:
    # New installations should create an Ingress rather than request a static IP.
    create: true
  SSL:
    # The TLS Secret is caller-managed; no chart creates it. Create it first:
    #   kubectl create secret tls example-tls-secret --key tls.key --cert tls.crt
    # This key is named nginxTLSSecret, not restyTLSSecret.
    nginxTLSSecret: example-tls-secret
```

Values are keyed by dependency name, so a block naming something the umbrella
does not depend on is silently ignored. Check `resty.enabled` and the other
`<name>.enabled` entries in the values table below for the current set.

`resty.ingress.create` and `resty.ingress.tls.enabled` (which defaults to true)
together require `resty.SSL.nginxTLSSecret`; the chart refuses to render without
it rather than emitting an Ingress with an empty `secretName`.

To deploy HeLx using the values.yaml use the following command.
```
helm -n $NAMESPACE --create-namespace install helx \
  oci://ghcr.io/helxplatform/helm-charts/helx --version 4.6.2 \
  --values values.yaml
```

## HeLx LDAP-only smoke test

The repository includes a values file and script for installing only the HeLx LDAP
service into an existing namespace. The script creates or updates the required
credentials Secret, prepares chart dependencies, installs the umbrella chart, and
waits for the HeLx LDAP StatefulSet and configuration hook. The namespace must
already exist:

```sh
NAMESPACE=ai-sb-test
helm registry login ghcr.io
export LDAP_ADMIN_PASSWORD='choose-an-admin-password'
export LDAP_CONFIG_ADMIN_PASSWORD='choose-a-config-password'
bash deploy/helm/helx-chart/examples/ldap-test.sh "$NAMESPACE" helx
```

The wrapper chart applies the HeLx `cn=config` LDIFs as a hardened
post-install/post-upgrade Job. See `services/helx-ldap/chart/README.md` for the
chart-specific Secret contract.

### Migrating an existing HeLx LDAP deployment

For a same-release Helm upgrade that must adopt an existing HeLx LDAP PVC, verify
and back up the live StatefulSet, PVC, and credentials Secret first. The
one-time values file is `examples/ldap-migration-values.yaml`; replace its
example names with the actual legacy PVC and Secret names. The pre-upgrade
migration hook automatically scales the prior HeLx LDAP StatefulSet to zero,
waits for its pods to terminate, and deletes only the old StatefulSet controller
with orphan propagation. The PVC and backing volume are retained, so no manual
scale-down or deletion is required. Do not attach an RWO claim to two
StatefulSets.

After the upgrade, verify that the PVC UID is unchanged and that the new
StatefulSet mounts the adopted claim through `claimName`. Disable both migration
flags on the next upgrade, but keep `helx-ldap.openldap.persistence.existingClaim`
set permanently. The optional Secret migration is a live Helm pre-upgrade hook;
it copies the old Secret into the canonical `openldap-credentials` target and
does not delete the old Secret.
You can view the README.md files for each subchart to see the variables that exist.

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ambassador.enabled | bool | `true` | enable/disable deployment of Ambassador |
| appstore-prepuller.enabled | bool | `true` | enable/disable deployment of appstore-prepuller |
| appstore-sockets.enabled | bool | `true` | enable/disable deployment of appstore websockets service |
| appstore.enabled | bool | `true` | enable/disable deployment of appstore |
| backup-pvc-cronjob.enabled | bool | `false` | enable/disable deployment of backup-pvc-cronjob |
| global.ambassador_service_name | string | `"ambassador"` |  |
| global.redis.existingSecret | string | `"redis-secret"` |  |
| global.redis.existingSecretPasswordKey | string | `"redis-password"` |  |
| global.restartr_api_service_name | string | `"helx-restartr-api-service"` |  |
| global.stdnfsPvc | string | `"stdnfs"` |  |
| helx-ldap.enabled | bool | `true` | enable/disable deployment of the HeLx LDAP service |
| ldap-sync.enabled | bool | `true` | enable/disable deployment of ldap-sync |
| image-utils.enabled | bool | `false` | enable/disable deployment of image-utils (imagepullsecret-patcher and imagepuller) |
| monitoring.enabled | bool | `false` | enable/disable deployment of monitoring (kube-prometheus-stack, cost-analyzer, etc.) |
| nfs-server.enabled | bool | `false` | enable/disable deployment of nfs-server |
| nfsrods.enabled | bool | `false` | enable/disable deployment of nfsrods |
| nginx.enabled | bool | `false` | enable/disable deployment of nginx |
| pod-reaper.enabled | bool | `true` | enable/disable deployment of pod-reaper |
| resty.enabled | bool | `true` | enable/disable deployment of resty |
| search.enabled | bool | `false` | enable/disable deployment of search |
| ui.enabled | bool | `true` | enable/disable deployment of helx-ui |
| user-mutator.enabled | bool | `false` | enable/disable deployment of the user-mutator admission webhook |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.11.0](https://github.com/norwoodj/helm-docs/releases/v1.11.0)
