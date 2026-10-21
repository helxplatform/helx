# Setting up Argo CD in a new cluster

This is the procedure for moving a cluster's HeLx deployments from
`make helm-deploy` to Argo CD, including taking over Helm releases that are
already running. It was first carried out on the Azure AI Sandbox cluster
(kube context `ai-sandbox`), starting with the `ai-sb-test` namespace, in
October 2026. Each section records what was done there and what to change for
another cluster.

> **Status (2026-10-20):** the repository side is done: sections 2, 6, and 7
> (the CI half), and the files in `deploy/argocd/`. External Secrets is
> installed on the Azure cluster (section 3). Steps that change the
> cluster, Vault, ACR, or GitHub settings are marked *(not done yet)*. Update
> each one as it is carried out. The open question is whether the cluster can
> reach Vault at all, since Vault is only reachable over the RENCI VPN
> (section 4).

## How the pieces fit

- Each HeLx namespace gets one Argo CD Application that deploys the whole
  umbrella chart (`helx`). Services are not split into separate Applications,
  because the umbrella is what pins every service chart and image version.
- The Applications are not written by hand. An ApplicationSet reads one small
  file per environment, `deploy/argocd/envs/<env>/config.yaml`, and creates an
  Application named `helx-<env>` for each.
- The ApplicationSet, the `helx` AppProject, and the External Secrets install
  live in `deploy/argocd/bootstrap/`. One root Application,
  `deploy/argocd/root.yaml`, is applied once with `kubectl` and keeps that
  folder synced, so after the first apply every change goes through Git.
- Each Application takes the chart from GHCR
  (`ghcr.io/helxplatform/helm-charts/helx`) and renders it with three values
  files, in this order:
  1. `deploy/helm/values/<cluster>/defaults/values.yaml`
  2. `deploy/helm/values/<cluster>/envs/<env>/values.yaml`
  3. `deploy/argocd/envs/<env>/values.yaml`, holding settings that only Argo CD
     needs (section 6)

  It also applies the plain manifests in `deploy/argocd/envs/<env>/manifests/`.
- Secrets come from HashiCorp Vault through the External Secrets Operator (ESO).
  The `~/helm-values/.../secrets.yaml` files used with `make helm-deploy` are
  not used by Argo CD.
- Argo CD reads `deploy/argocd/` and the values files from the `develop` branch,
  so nothing here takes effect until it is merged there.

```
deploy/argocd/
├── root.yaml                          applied by hand, once per cluster
├── bootstrap/                         synced by root
│   ├── project-helx.yaml              AppProject: allowed repos and namespaces
│   ├── external-secrets.yaml          Application: the ESO Helm chart
│   └── applicationset-helx.yaml       one Application per envs/<env>/
└── envs/
    └── ai-sb-test/
        ├── config.yaml                cluster, namespace, chart and version
        ├── values.yaml                Argo CD-only values (third values file)
        └── manifests/
            ├── secret-store.yaml      how ESO logs in to Vault
            └── postgres-secrets.yaml  ExternalSecrets the charts can't render
```

## 1. Take stock of the cluster

Before changing anything, record what is running. These commands only read.

```sh
CONTEXT=ai-sandbox

# Every Helm release, with its chart version
helm --kube-context "$CONTEXT" list -A

# Namespaces, including whether argocd already exists
kubectl --context "$CONTEXT" get ns

# Argo CD's version
kubectl --context "$CONTEXT" -n argocd get deploy argocd-server \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'

# Which CRDs are installed (Argo CD, External Secrets, cert-manager)
kubectl --context "$CONTEXT" get crd | grep -i -E 'argoproj|external-secrets|cert-manager'

# Images running in the namespace you plan to take over
kubectl --context "$CONTEXT" -n ai-sb-test get pods -o \
  jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .spec.containers[*]}{.image}{" "}{end}{"\n"}{end}'

# Secrets in that namespace and who manages them (names only, no contents)
kubectl --context "$CONTEXT" -n ai-sb-test get secrets -o \
  jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.labels.app\.kubernetes\.io/managed-by}{"\n"}{end}'
```

What this showed on the Azure cluster:

| Namespace    | What runs there                                                                                          |
| ------------ | -------------------------------------------------------------------------------------------------------- |
| `ai-sb-test` | One `helx` release, chart `helx-5.1.1-local` (packaged locally with `make build-helx-chart`).            |
| `default`    | The older layout: `helx` chart 4.5.10 plus separate `ldap-sync`, `openldap`, `user-mutator`, and `appstore-prepuller` releases. |
| `infra`      | cert-manager, ingress-nginx, gpu-operator.                                                                |
| `argocd`     | Argo CD v3.5.5, installed from manifests shortly before this work. No Applications yet.                   |

External Secrets was not installed. `gatekeeper-system` exists, so Gatekeeper
policies may reject some objects; check its audit results if a sync fails
with an admission error.

The HeLx images in `ai-sb-test` come from ACR
(`aisandboxrencitgt.azurecr.io/helxplatform/...`, tag `azure-demo-deploy-1`),
not from Harbor, because this cluster cannot reliably pull from Harbor. Charts
are different: the cluster and Argo CD can reach GHCR, so the chart comes from
there like everywhere else. On a cluster that can pull from
`containers.renci.org`, skip the ACR parts of section 7.

`ai-sb-test` was chosen first because it already runs the current umbrella
chart. A namespace still on the old split layout (like `default` here) must
first be migrated to the umbrella with `make helm-deploy`, following
[DeploymentMigration.md](DeploymentMigration.md), before Argo CD takes it over.

## 2. Finish chart migrations before handing over

Several charts have one-time migration switches. All of them are off by
default, and they stay in the charts for older deployments that still need
them:

| Value                                  | Chart     |
| -------------------------------------- | --------- |
| `helx-ldap.secret.migration.enabled`    | helx-ldap |
| `helx-ldap.openldap.migration.enabled`  | helx-ldap |
| `ldap-sync.postgres.migration.enabled`  | ldap-sync |
| `ldap-sync.secret.migration.enabled`    | ldap-sync |
| `appstore.secret.migration.enabled` and other `secret.migration.enabled` values | appstore and other helx-common charts |

These migrations need a real `helm upgrade`: they read live objects with
Helm's `lookup`, and some refuse to render unless the deploy is an upgrade.
Argo CD renders charts with `helm template`, where `lookup` finds nothing and
every deploy looks like a fresh install. So:

- Run any pending migration with `make helm-deploy` first.
- Make sure none of these values is set to `true` in the values files that
  Argo CD will use. Search for them before handing over:

  ```sh
  grep -rn -A2 'migration:' deploy/helm/values/<cluster>/ deploy/argocd/envs/<env>/
  ```

On the Azure cluster none was enabled for `ai-sb-test`. As a safeguard,
`deploy/argocd/envs/ai-sb-test/values.yaml` sets
`appstore.secret.migration.enabled: false` explicitly, because appstore's
chart default is `true`.

## 3. Install External Secrets

`deploy/argocd/bootstrap/external-secrets.yaml` installs ESO chart 2.13.0 into
the `external-secrets` namespace. The root Application (section 9) applies it
along with the rest of `bootstrap/`. ESO doesn't depend on anything else in
this procedure, though, so it can be applied on its own first. That is what
was done on the Azure cluster, so the SecretStore could be tested before the
bootstrap:

```sh
kubectl --context ai-sandbox apply -f deploy/argocd/bootstrap/external-secrets.yaml
```

The file already sets `namespace: argocd`. Automated sync is on, so Argo CD
installs ESO straight away. When `root.yaml` is applied later, it takes over
this same Application (same name in `argocd`) without reinstalling anything.

That file names two namespaces. The
Application object itself lives in `argocd` (`metadata.namespace`), because
Argo CD only picks up Applications in its own namespace. ESO's pods and other
resources go into `external-secrets` (`spec.destination.namespace`), which
`CreateNamespace=true` creates on the first sync. Every Application in
`deploy/argocd/` follows the same pattern; for example, `helx-ai-sb-test`
lives in `argocd` and deploys into `ai-sb-test`. It uses server-side apply because ESO's
CRDs are too large for a normal `kubectl apply`. It also ignores the CA bundles
that ESO's cert-controller writes at runtime, which would otherwise keep the
Application out of sync.

Before applying it on a new cluster, check that nothing would conflict or be
rejected:

- no `external-secrets` namespace and no `*.external-secrets.io` CRDs yet
  (`kubectl get crd | grep external-secrets`)
- the cluster can pull `ghcr.io/external-secrets/external-secrets`
- no admission policy blocks ESO. On the Azure cluster, Gatekeeper enforces
  only "no privileged containers" and "no privilege escalation", and ESO's
  three containers set neither; the other Azure Policy constraints there only
  record violations:

  ```sh
  kubectl get constraints -o \
    jsonpath='{range .items[?(@.spec.enforcementAction=="deny")]}{.kind}{"\n"}{end}'
  ```

Check that it worked:

```sh
# Synced and Healthy, at revision 2.13.0
kubectl --context ai-sandbox -n argocd get application external-secrets

# external-secrets, external-secrets-cert-controller and
# external-secrets-webhook, each 1/1 Running
kubectl --context ai-sandbox -n external-secrets get pods
```

ESO adds cluster-wide objects: CRDs, cluster roles, and two validating
webhooks. The webhooks only check ESO's own objects (SecretStores and
ExternalSecrets), so nothing else on the cluster is affected.

To upgrade ESO later, change `targetRevision` in that file.

## 4. Connect External Secrets to Vault *(not done yet)*

Each HeLx namespace gets its own SecretStore named `vault`, defined in
`deploy/argocd/envs/<env>/manifests/secret-store.yaml`. Every ExternalSecret
the HeLx charts render points at a SecretStore with that name by default. A
namespaced SecretStore, rather than one cluster-wide store, means each
namespace can only read its own Vault entries.

### Can the cluster reach Vault?

ESO runs in the cluster and connects to Vault on every refresh, so pods in the
cluster need a network path to Vault. RENCI's Vault is usually only reachable
over the VPN, so on the Azure cluster this has to be confirmed before anything
else in this section. Run this from a throwaway pod (it only asks Vault whether
it is up):

```sh
kubectl --context ai-sandbox -n ai-sb-test run vault-check --rm -i \ 
  --restart=Never --image=curlimages/curl:8.10.1 -- \
  curl -sS --max-time 10 https://vault.apps.renci.org/v1/sys/health
```

- **JSON comes back:** the cluster can reach Vault; carry on below.
- **Timeout or "could not resolve host":** it can't. `vault.apps.renci.org`
  resolves to a public address (152.54.15.132), so the usual fix is for
  the team that runs Vault to allow connections from the cluster's outbound
  IP address (next section). If they can't, the network administrators need
  to route the cluster's outbound traffic to Vault (for example a
  site-to-site VPN or private link from the cluster's Azure network to
  RENCI). Until one of these is done, External Secrets can't fill any Secret here.

**If the cluster can never reach Vault**, keep the secret values somewhere it
can reach instead, such as Azure Key Vault. External Secrets supports both, so
the charts would render the same ExternalSecrets and produce the same
Kubernetes Secrets, and sections 5–11 would still apply with a different
place to store the values. Only two things would change:

1. `manifests/secret-store.yaml`: the SecretStore's `provider` becomes
   `azurekv` (Azure Key Vault, logging in with workload identity) instead of
   `vault`. Keep the name `vault`, or the charts' ExternalSecrets would need
   `secretStoreRef.name` changed as well.
2. The name each value is stored under. Every `remoteRef` and `extract.key`
   in `deploy/argocd/envs/<env>/values.yaml` and
   `manifests/postgres-secrets.yaml` is a Vault path such as
   `helx/ai-sb-test/helx-appstore-secrets`. Azure Key Vault names can't
   contain `/`, so each would become something like
   `helx-ai-sb-test-helx-appstore-secrets`. Each Azure Key Vault secret
   would hold that Secret's keys as one JSON object, which ESO's `extract`
   splits back into separate keys.

### Finding the cluster's outbound IP address

Connections from pods leave the cluster through one public IP address, which
is what Vault's allow-list needs. With `az` logged in to the cluster's
subscription:

```sh
# How the cluster sends outbound traffic, and which IP resource it uses
az aks show -g renci-ai-sandbox -n ai-sandbox --query \
  '{outboundType: networkProfile.outboundType,
    lbIps: networkProfile.loadBalancerProfile.effectiveOutboundIPs[].id,
    natIps: networkProfile.natGatewayProfile.effectiveOutboundIPs[].id}'

# The address of each IP resource listed above
az network public-ip show --ids <id from above> --query ipAddress -o tsv
```

On the Azure cluster `outboundType` is `loadBalancer`, with one outbound IP:
**9.169.134.173** (Standard SKU, so it is static). No node pool gives its nodes
their own public IPs, so all pod traffic leaves through that address. The
`outboundType` decides where to look:

- `loadBalancer`: the IPs under `lbIps`, as above.
- `managedNATGateway` or `userAssignedNATGateway`: the IPs under `natIps`.
- `userDefinedRouting`: traffic leaves through a firewall or appliance the
  network team runs; ask them for its address.

To confirm from inside the cluster (prints the address the internet sees):

```sh
kubectl --context ai-sandbox -n ai-sb-test run egress-ip --rm -i --restart=Never \
  --image=curlimages/curl:8.10.1 -- curl -sS --max-time 10 https://ifconfig.me
```

AKS created and manages this IP (it is tagged `aks-slb-managed-outbound-ip`).
It is a separate Azure resource from the nodes, so node restarts, node image
upgrades, and Kubernetes upgrades leave it alone. On the Azure cluster it was
created on 2026-04-27, along with the cluster, and was still unchanged in
October 2026 after automatic node image upgrades (nodes were on July 2026
images). It changes if someone changes the cluster's outbound settings, for
example the number of managed outbound IPs or the outbound type. If the
cluster is recreated, it gets a new address and the allow-list must be
updated. Microsoft's stop/start documentation warns only that the API
server's IP may change after `az aks start`; it doesn't mention the outbound
IP, so re-check it after a stop and start. Don't confuse it with
`pubip-ingress-nginx` in the same resource group: that is the inbound address
for the ingress controller, not the one pods' outbound traffic uses. For an address that survives all of
that, create a public IP (or prefix) yourself and attach it with
`az aks update --load-balancer-outbound-ips <id>` before asking for the
allow-list.

### Vault login: JWT auth

ESO logs in to Vault with a short-lived token for the `external-secrets-vault`
ServiceAccount in the namespace. The file uses Vault's **JWT** auth, not its
Kubernetes auth, because JWT auth never needs Vault to connect to the
cluster. Kubernetes auth would need Vault to call the cluster's API server,
which a Vault behind the VPN may not be able to do. With JWT auth Vault checks
the token's signature against the cluster's public OIDC issuer. Find the
issuer with:

```sh
kubectl --context ai-sandbox get --raw /.well-known/openid-configuration | jq -r .issuer
```

For the Azure cluster it is
`https://eastus2.oic.prod-aks.azure.com/58b3d54f-16c9-42d3-af08-1fcabd095666/b2c653e1-be86-434e-8990-2e07518d395e/`.

Ask the Vault administrators to set up the following. The names match
`secret-store.yaml`; any of them can change, as long as the file matches.

```sh
# A JWT auth mount for this cluster
vault auth enable -path=jwt-ai-sandbox jwt
vault write auth/jwt-ai-sandbox/config \
  oidc_discovery_url="<issuer from above>" \
  bound_issuer="<issuer from above>"

# Read access to this namespace's entries only
vault policy write helx-ai-sb-test - <<'POLICY'
path "secret/data/helx/ai-sb-test/*" {
  capabilities = ["read"]
}
POLICY

# A role that only the external-secrets-vault ServiceAccount in ai-sb-test can use
vault write auth/jwt-ai-sandbox/role/helx-ai-sb-test \
  role_type=jwt \
  user_claim=sub \
  bound_audiences=vault \
  bound_subject="system:serviceaccount:ai-sb-test:external-secrets-vault" \
  token_policies=helx-ai-sb-test \
  token_ttl=1h
```

`oidc_discovery_url` needs Vault to reach the issuer URL over the internet.
If Vault has no internet access either, configure the mount with the
cluster's signing keys instead of a discovery URL. Vault then needs no network
at all, but the keys must be updated whenever AKS rotates them:

```sh
kubectl --context ai-sandbox get --raw /openid/v1/jwks > ai-sandbox-jwks.json
# convert each key to PEM, then:
vault write auth/jwt-ai-sandbox/config \
  jwt_validation_pubkeys=@ai-sandbox.pem bound_issuer="<issuer from above>"
```

You will also need write access to `secret/helx/ai-sb-test/` for section 5.

Then replace the `TODO(vault)` placeholders in `secret-store.yaml` (`server`,
the KV mount `path`, and `auth.jwt.path`) and commit.

## 5. Move each secret into Vault *(not done yet)*

Every Secret that the chart used to create gets one Vault entry with the same
name and the same keys, under `helx/<env>/`. The values files in section 6
already point at these paths. For `ai-sb-test`:

| Kubernetes Secret                 | Vault entry (in the KV mount)               | Written by                                        |
| --------------------------------- | ------------------------------------------- | ------------------------------------------------- |
| `helx-appstore-secrets`           | `helx/ai-sb-test/helx-appstore-secrets`     | appstore chart (ExternalSecret `helx-appstore`)   |
| `pgadmin-env`                     | `helx/ai-sb-test/pgadmin-env`               | appstore chart                                    |
| `helx-postgresql`                 | `helx/ai-sb-test/helx-postgresql`           | `manifests/postgres-secrets.yaml`                 |
| `helx-appstore-sockets`           | `helx/ai-sb-test/helx-appstore-sockets`     | appstore-sockets chart                            |
| `openldap-credentials`            | `helx/ai-sb-test/openldap-credentials`      | helx-ldap chart (ExternalSecret `helx-helx-ldap`) |
| `helx-ldap-sync-secrets`          | `helx/ai-sb-test/helx-ldap-sync-secrets`    | ldap-sync chart (ExternalSecret `helx-ldap-sync`) |
| `helx-ldap-sync-postgres`         | `helx/ai-sb-test/helx-ldap-sync-postgres`   | `manifests/postgres-secrets.yaml`                 |
| `helx-user-mutator-tls`           | `helx/ai-sb-test/helx-user-mutator-tls`     | user-mutator chart                                |
| `helx-user-mutator-ldap-password` | `helx/ai-sb-test/helx-user-mutator-ldap-password` | user-mutator chart                          |

When taking over a running release, copy the **live** values; don't generate
new ones. The databases were initialised with the live passwords, and the
webhook's CA bundle in `values.yaml` matches the live certificate. This loop
copies each Secret's decoded data straight into Vault, without printing it.
Run it from a machine on the VPN, logged in to Vault (`vault login`) with
write access to `secret/helx/ai-sb-test/`:

```sh
CONTEXT=ai-sandbox
NAMESPACE=ai-sb-test
MOUNT=secret
for name in helx-appstore-secrets pgadmin-env helx-postgresql \
            helx-appstore-sockets openldap-credentials helx-ldap-sync-secrets \
            helx-ldap-sync-postgres helx-user-mutator-tls \
            helx-user-mutator-ldap-password; do
  kubectl --context "$CONTEXT" -n "$NAMESPACE" get secret "$name" -o json \
    | jq '.data | map_values(@base64d)' \
    | vault kv put -mount="$MOUNT" "helx/$NAMESPACE/$name" -
done
```

Check that each entry has the right keys (this lists key names only):

```sh
vault kv get -mount="$MOUNT" -format=json "helx/$NAMESPACE/helx-postgresql" | jq '.data.data | keys'
```

For a brand-new environment with nothing to copy, create each entry with the
keys the chart requires. Each chart's `values.yaml` lists them under its
`secret.values` comments.

## 6. Make the chart values safe for Argo CD *(done in the repository)*

Argo CD renders the chart with `helm template` and compares the result with the
cluster on every refresh. Anything that comes out different on each render
looks permanently out of sync, and with automatic sync it is replaced every
time. For a password, that means the app and its database stop agreeing.

The test for this is to render the chart twice with exactly the values files
the Application uses, and compare the two outputs:

```sh
render() {
  helm template helx deploy/helm/helx-chart -n ai-sb-test --skip-tests \
    -f deploy/helm/values/azure/defaults/values.yaml \
    -f deploy/helm/values/azure/envs/ai-sb-test/values.yaml \
    -f deploy/argocd/envs/ai-sb-test/values.yaml
}
render > /tmp/render-1.yaml
render > /tmp/render-2.yaml
cmp /tmp/render-1.yaml /tmp/render-2.yaml && echo identical
```

(`deploy/helm/helx-chart/charts/` must hold the dependency archives; any
earlier `make build-helx-chart` leaves them there.)

Without the third values file, six objects differed between renders:

| Object                                    | Why it changed                                    | Fix in `deploy/argocd/envs/ai-sb-test/values.yaml` |
| ----------------------------------------- | ------------------------------------------------- | -------------------------------------------------- |
| Secret `helx-appstore-sockets`            | `PUBLISHER_SECRET` from `randAlphaNum`            | `appstore-sockets.secret.mode: externalSecret`      |
| Secret `pgadmin-env`                      | pgAdmin password from `randAlphaNum`              | `appstore.pgadmin.secret.mode: externalSecret`      |
| Secret `helx-postgresql`                  | bitnami subchart generates a password             | `appstore.postgresql.global.postgresql.auth.existingSecret`, filled by `manifests/postgres-secrets.yaml` |
| Secret `helx-ldap-sync-postgres`          | postgres subchart generates a password            | `ldap-sync.postgres.auth.existingSecret`, filled by `manifests/postgres-secrets.yaml` |
| Secret `helx-user-mutator-tls`            | `secret.mode: generate` makes a new CA each time  | `user-mutator.secret.mode: externalSecret`          |
| MutatingWebhookConfiguration (user-mutator) | its `caBundle` is that new CA                   | `user-mutator.webhook.caBundle`, copied from the live webhook |

The remaining chart-managed Secrets (`helx-appstore-secrets`,
`openldap-credentials`, `helx-ldap-sync-secrets`,
`helx-user-mutator-ldap-password`) were stable only because they read their
values from the secrets files. Under Argo CD they move to Vault too. With the
third values file, the two renders are identical, and the chart renders no
Secret objects at all.

The CA bundle is public, so it is committed. It was read from the live webhook:

```sh
kubectl --context ai-sandbox get mutatingwebhookconfiguration \
  helx-user-mutator-webhook-ai-sb-test \
  -o jsonpath='{.webhooks[0].clientConfig.caBundle}'
```

It is valid until 2036-10-11. When it is replaced, update the Vault entry
`helx-user-mutator-tls` and `webhook.caBundle` together.

Two other Helm features behave differently under Argo CD; neither needed a
change:

- `post-install,post-upgrade` hooks (`helx-ldap` configure Job, `ldap-sync`
  search bootstrap) become Argo CD PostSync hooks and run after **every**
  sync. Both check before changing anything, so repeating them is safe.
- `helm test` Pods are left out with `skipTests: true` in the ApplicationSet.

Compared with the Helm render, the only differences are Secrets becoming
ExternalSecrets and the webhook's `caBundle`, which now matches the live one.
No Deployment or StatefulSet template changes, so the takeover itself restarts
nothing. Pods do roll when the first ACR candidate changes the image tags.

## 7. Publish a chart Argo CD can follow, and images the cluster can pull *(CI done; ACR setup not done yet)*

### The chart: numbered candidates on GHCR

For a test environment that follows `develop`, the chart's version must
change on every push. Argo CD caches a chart by its version string, so it
never notices that the mutable `5.1.1-develop` tag on GHCR was overwritten.

So `develop.yml` now publishes every candidate twice to
`oci://ghcr.io/helxplatform/helm-charts/helx`:

- `publish-candidate`: the mutable `<version>-develop`, as before
- `publish-numbered-candidate`: the same content as
  `<version>-develop.<run number>` (for example `5.1.1-develop.214`),
  published once and never overwritten

`deploy/argocd/envs/ai-sb-test/config.yaml` follows GHCR with the version range
`>=0.0.0-0`, which means "the newest version, prereleases included". Run
numbers compare as numbers, so `develop.10` sorts above `develop.9`, and
raising the umbrella version (`5.2.0-develop.1`) sorts above every
`5.1.1-develop.*`. This was checked with `helm search repo --version` against
a throwaway index.

The range also matches releases. Right after a release such as `5.1.1` is
cut, that release is the newest version until the first `develop` push with a
higher umbrella version, so the test environment runs it. That is
intentional, and it is why released images are copied to ACR too (below).
CI publishes and copies released images only as `v<appVersion>`, so every
chart's default image tag must be `v<appVersion>` as well. ldap-sync's default
was the bare appVersion (`ldap-sync:4.4.2`); it was fixed during this work
(chart 3.0.4, not yet released at the time).

### The images: copies in ACR

This cluster cannot reliably pull from Harbor, so every image this repository
builds is copied to ACR, and the cluster pulls the copy:

- `mirror-images-acr` in `develop.yml` copies each `develop-<sha>` image, and
  the job of the same name in `publish.yml` copies each released
  `v<appVersion>` image, from Harbor to
  `<ACR_LOGIN_SERVER>/helxplatform/<image>`. Both use
  `.github/actions/mirror-image`, which copies rather than rebuilds, so each
  copy has the same digest as Harbor's. Both run only when the GitHub
  repository variable `ACR_LOGIN_SERVER` is set.
- `publish-numbered-candidate` waits for `mirror-images-acr`, so Argo CD never
  sees a numbered candidate before its images are in ACR.
- The chart still names Harbor repositories.
  `deploy/helm/values/azure/defaults/values.yaml` repoints the `repository` of
  every image this repository builds at
  `aisandboxrencitgt.azurecr.io/helxplatform/...`. The tag still comes from the
  chart: `develop-<sha>` for a candidate, `v<appVersion>` for a release. When
  an image is added to `.github/ci/images.yaml`, add its repository there too.
  The comment at the top of that file has the command that prints every path.

Images this repository doesn't build were already handled before this work.
Bitnami PostgreSQL, os-shell, openresty, and unc-group-x already point at ACR
in the same file. ldap-sync's `docker.io/postgres` and pod-reaper's
`helxplatform/pod-reaper` come from Docker Hub, which this cluster can reach.

To set it up (someone with ACR and GitHub admin rights):

1. Create an ACR token CI can push with, limited to `helxplatform/`:

   ```sh
   ACR=aisandboxrencitgt
   az acr scope-map create --registry "$ACR" --name helx-ci-push \
     --repository 'helxplatform/*' content/read content/write
   az acr token create --registry "$ACR" --name helx-ci --scope-map helx-ci-push
   ```

   Wildcard repository scopes need a recent ACR. If `az` rejects them, list the
   repositories explicitly: each `repository` in `.github/ci/images.yaml`,
   under `helxplatform/`.

2. In the GitHub repository settings, add the variable
   `ACR_LOGIN_SERVER=aisandboxrencitgt.azurecr.io` and the secrets
   `ACR_USERNAME` (the token name, `helx-ci`) and `ACR_PASSWORD` (one of its
   passwords).
3. Get every image into ACR before Argo CD is bootstrapped: push to `develop`
   (or run "Develop channel" from the Actions tab) for the candidate images,
   and let the next push to `main` copy the released ones. Until then, a
   numbered candidate published before the variable was set names images
   that are not in ACR.

## 8. Give Argo CD access to the repositories *(not done yet)*

- **GitHub** (`https://github.com/helxplatform/helx.git`) is public, so it
  needs no credentials.
- **GHCR** (`ghcr.io/helxplatform/helm-charts`): pulling a chart worked without
  credentials, but GHCR refused an anonymous tag listing, and Argo CD lists
  tags to resolve the `>=0.0.0-0` range. Register it with a GitHub token that
  has only `read:packages`, ideally from a bot account rather than a
  person's. The `url` has no `oci://` prefix and must equal `chart.repoURL`
  in the env's `config.yaml`:

  ```sh
  kubectl --context ai-sandbox -n argocd create secret generic repo-ghcr-helm-charts \
    --from-literal=type=helm \
    --from-literal=name=ghcr-helm-charts \
    --from-literal=url=ghcr.io/helxplatform/helm-charts \
    --from-literal=enableOCI=true \
    --from-literal=username=<github user> \
    --from-literal=password='<token>'
  kubectl --context ai-sandbox -n argocd label secret repo-ghcr-helm-charts \
    argocd.argoproj.io/secret-type=repository
  ```

- **ACR** needs nothing from Argo CD, which never pulls images. The cluster's
  nodes already pull from ACR (the namespace's `aisandboxrencitgt-creds` pull
  secret is in `global.imagePullSecrets`).

## 9. Bootstrap Argo CD from `deploy/argocd/` *(not done yet)*

Before this step, check that:

- the cluster can reach Vault and `secret-store.yaml` has no `TODO(vault)`
  left (section 4)
- every Vault entry exists (section 5)
- the images are in ACR (section 7)
- the GHCR repository Secret exists (section 8)

The bootstrap reads `develop`, so merge this work to `develop` first. To try it
from a branch before merging, change `targetRevision` in `root.yaml`,
`revision` in `bootstrap/applicationset-helx.yaml`, and `valuesRef` in the
env's `config.yaml` to the branch, and change them back before merging.

```sh
kubectl --context ai-sandbox apply -n argocd -f deploy/argocd/root.yaml
```

Then wait for External Secrets to be running, and check that the SecretStore
can log in to Vault:

```sh
kubectl --context ai-sandbox -n argocd get applications
kubectl --context ai-sandbox -n external-secrets get pods
kubectl --context ai-sandbox -n ai-sb-test get secretstore vault
```

The SecretStore only exists once `helx-ai-sb-test` has synced, which is the
next section. `READY` must be `True` before any ExternalSecret can fill a
Secret. If it isn't, `kubectl describe secretstore vault` gives Vault's error.

`helx-ai-sb-test` starts with automatic sync off (`autoSync: false`), so
nothing in `ai-sb-test` changes until someone presses Sync.

## 10. Take over the existing Helm release *(not done yet)*

Argo CD takes over a Helm release by applying the same objects under the same
names: same release name (`releaseName: helx`), same namespace. It adds its
tracking annotation to each object on the first sync. Helm's own release
record (`sh.helm.release.v1.helx.*` Secrets) is not touched.

1. In the Argo CD UI, open `helx-ai-sb-test` and press **App Diff**. Expect:
   - image tags changing from `azure-demo-deploy-1` to `develop-<sha>`
   - ExternalSecrets, the SecretStore, and its ServiceAccount being added
   - the chart-managed Secrets missing from Git. They show as present in the
     cluster but not in Git; they are **not** deleted, because Argo CD never
     prunes objects it didn't create, and there's no automatic pruning yet.

   Anything else is worth understanding before syncing.
2. Press **Sync**.
3. Check every ExternalSecret:

   ```sh
   kubectl --context ai-sandbox -n ai-sb-test get externalsecrets
   ```

   ESO with `creationPolicy: Owner` may refuse to write over a Secret it
   didn't create (status `SecretSyncedError`, mentioning ownership). For each
   one that does, delete the old Secret and tell ESO to sync immediately.
   Pods that are already running keep working, because they read the Secret
   at start-up. Only a pod starting in the few seconds between the two
   commands would fail:

   ```sh
   kubectl --context ai-sandbox -n ai-sb-test delete secret <name>
   kubectl --context ai-sandbox -n ai-sb-test annotate externalsecret <externalsecret> \
     force-sync="$(date +%s)" --overwrite
   ```

4. Once everything is Synced and Healthy, stop anyone from upgrading the
   release with Helm by accident: delete Helm's release record. **Do not run
   `helm uninstall`**, which deletes the workloads. Deleting the record only
   makes `helm list` forget the release:

   ```sh
   kubectl --context ai-sandbox -n ai-sb-test delete secret -l owner=helm,name=helx
   ```

5. When the takeover has run cleanly for a while, set `autoSync: true` in
   `config.yaml`. New `develop` candidates then deploy on their own.

## 11. Verify *(not done yet)*

- The Application shows the resolved chart version (for example
  `5.1.1-develop.214`), not the range. If it shows an error about the range,
  Argo CD can't list GHCR's tags; check the repository Secret from section 8.
- `kubectl -n ai-sb-test get pods` shows every pod running the `develop-<sha>`
  images from ACR.
- `kubectl -n ai-sb-test get externalsecrets` shows every one `SecretSynced`.
- The Application stays Synced after a few minutes. An object that keeps
  drifting means something still renders differently each time (section 6),
  or a controller edits a field after apply. The second case is fixed with
  `ignoreDifferences` in the ApplicationSet.
- No `helx-*-test-connection` Pods were created.
- Log in to the HeLx UI and launch an app, which exercises appstore, the
  database, LDAP, and the user-mutator webhook.

## Adding another environment or cluster

1. Sections 1 and 2 for the namespace.
2. Copy `deploy/argocd/envs/ai-sb-test/` to `deploy/argocd/envs/<env>/`. The
   folder name must match `deploy/helm/values/<cluster>/envs/<env>/`. Then edit
   `config.yaml` (a production environment pins an exact released `version`
   and sets `valuesRef: main`), the Vault paths and CA bundle in
   `values.yaml`, and `manifests/` (the Vault role and JWT mount).
3. Add the namespace to `destinations` in `bootstrap/project-helx.yaml`.
4. Re-run the double render from section 6 for the new values files.
5. Sections 4 and 5 for its Vault role and entries, then 10 and 11.

On a new cluster, Argo CD itself and section 8 come first, then `root.yaml`
(section 9). A cluster that pulls from Harbor needs no ACR steps and no
repository overrides in its values; one that can't pull from Harbor needs its
own copy of section 7's ACR setup, since the CI jobs copy to a single registry.
