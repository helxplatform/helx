# Setting up Argo CD in a new cluster

This is the procedure for moving a cluster's HeLx deployments from
`make helm-deploy` to Argo CD, including taking over Helm releases that are
already running. The commands use the Azure AI Sandbox cluster (kube context
`ai-sandbox`) and its `ai-sb-test` namespace as the example; substitute your
own cluster and namespace. Where the Azure cluster needs something other
clusters don't (pulling images from ACR), the section says so.

> **Status and hand-off (2026-10-29).** This block, and the *(done)* /
> *(not done yet)* markers on the section headings, track the first run of
> this procedure, on the Azure cluster's `ai-sb-test` namespace. Delete them
> once that run is finished; everything else in this document is the
> procedure itself.
>
> **Where it stands:**
>
> - **Sections 1 and 2:** done. `ai-sb-test` runs the umbrella chart as the Helm
>   release `helx`, and no migration switch is on.
> - **Section 3:** done. The `external-secrets` Application is Synced and
>   Healthy.
> - **Section 4:** done. The ClusterSecretStore `vault` is `READY`, the
>   `vault-token` Secret exists, and `vault-token-renewal` runs every Monday
>   at 06:17 UTC.
> - **Section 5:** done. The nine entries are uploaded to the `helx` mount
>   under `dev/azure/ai-sb-test/`, the comparison matched (only the expected
>   `tls.key` newline), the new `secrets.yaml` is listed in
>   `LOCAL_VALUES_FILE`, and `dist/vault-secrets/` is deleted. The
>   chart-managed Secrets in `ai-sb-test` were last written on 2026-10-14, so
>   the Helm upgrades since then (revision 7, 2026-10-27) haven't changed them.
> - **Section 6:** done in the repository.
> - **Section 7:** the CI changes are on the branch `argocd-setup`, not yet
>   merged, so they don't run yet. ACR (`aisandboxrencitgt`, Standard SKU,
>   public network access, no firewall) passes step 1's check and has no
>   tokens yet. Steps 2–4 (token, password, GitHub variable and secrets) are
>   not done. Every built image's `helxplatform/` repository already exists in
>   ACR, but only with hand-pushed `azure-deploy-*` tags, which is what
>   `ai-sb-test` runs now; no `develop-<sha>` or `v<appVersion>` tags yet
>   (step 5).
> - **Section 8:** not done; there's no GHCR repository Secret in Argo CD.
> - **Section 9:** waiting on the merge. `argocd-setup` is to be merged to
>   `develop` after the next release is cut. Argo CD reads `develop`, so
>   applying `root.yaml` before then would find nothing.
> - **Sections 10 and 11:** not done. No HeLx Application or ExternalSecret
>   exists yet. `ai-sb-test` is still the Helm release `helx`, chart
>   `helx-5.1.1-local`.
>
> **Open questions and follow-ups:**
>
> - helx-common drops the final newline of a chart-managed Secret's
>   alphabetically last value (see step 4 of "Taking over a running
>   release"). The fix touches every chart that uses helx-common and is being
>   done separately.
> - Whether External Secrets takes over the existing chart-made Secrets, or
>   refuses because it didn't create them, is only known after the first sync
>   (section 10, step 3).
>
> **Ground rules for whoever continues, including an AI assistant:**
>
> - Treat the cluster as read-only (`get`, `describe`, `logs`); the person
>   running the procedure applies, deletes, and execs.
> - Never open or print the files under `dist/vault-secrets*` or any Vault
>   values; list names and keys only.
> - Don't write to Vault, ACR, Harbor, or GitHub settings. Test against fakes
>   (the tests use a fake `vault` on `PATH`).
> - Commit only when asked.
> - Keep this document a procedure: results of a run belong in this block,
>   not in the sections.

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
  The `secrets.yaml` used with `make helm-deploy` (for example
  `~/helm-values/.../helx/secrets.yaml`) is not used by Argo CD.
- Argo CD reads `deploy/argocd/` and the values files from the `develop` branch,
  so nothing here takes effect until it is merged there.

Where everything lives, outside `deploy/argocd/`:

- `deploy/helm/values/<cluster>/` holds the first two values files. The Azure
  cluster's `defaults/values.yaml` also points every image at ACR (section 7).
- `deploy/helm/vault-secrets-map.yaml` maps each Secret to its Vault entry and
  its Helm values. `.github/scripts/vault_secrets.py` and its tests, behind
  `make helm-secrets-to-vault`, `vault-secrets-to-helm`,
  `vault-secrets-from-cluster` and `vault-secrets-upload`, use it (section 5).
  `make help-local-dev` describes the targets.
- `.github/workflows/develop.yml` and `publish.yml` publish the numbered
  candidates and copy images to ACR, using `.github/actions/mirror-image`
  (section 7).
- `AGENTS.md`, under "Argo CD" and "Candidate channels", has the rules for
  changing any of this.

```
deploy/argocd/
├── root.yaml                          applied by hand, once per cluster
├── bootstrap/                         synced by root
│   ├── project-helx.yaml              AppProject: allowed repos and namespaces
│   ├── external-secrets.yaml          Application: the ESO Helm chart
│   ├── vault-cluster-secret-store.yaml  how ESO logs in to Vault
│   ├── vault-token-renewal.yaml       weekly CronJob that renews ESO's Vault token
│   └── applicationset-helx.yaml       one Application per envs/<env>/
└── envs/
    └── ai-sb-test/
        ├── config.yaml                cluster, namespace, chart and version
        ├── values.yaml                Argo CD-only values (third values file)
        └── manifests/
            └── postgres-secrets.yaml  ExternalSecrets the charts can't render
```

## 1. Take stock of the cluster *(done)*

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

What to look for in the output:

- **Which layout each HeLx namespace uses.** A namespace with a single `helx`
  release runs the current umbrella chart and can be taken over directly. A
  namespace with separate `ldap-sync`, `openldap`, `user-mutator`, or
  `appstore-prepuller` releases is on the older split layout. Migrate it to
  the umbrella with `make helm-deploy` first, following
  [DeploymentMigration.md](DeploymentMigration.md).
- **The Helm release name** of the umbrella (`helx` in the examples). Argo CD
  must use the same name (section 10).
- **Whether External Secrets is already installed** (`*.external-secrets.io`
  CRDs). Section 3 assumes it isn't.
- **Whether `gatekeeper-system` exists.** If it does, Gatekeeper policies may
  reject some objects. Check its enforced constraints (section 3), and its
  audit results if a sync fails with an admission error.
- **Where the images come from.** If they come from ACR rather than Harbor
  (`containers.renci.org`), the cluster can't reliably pull from Harbor, and
  section 7's ACR steps apply. Charts are different: Argo CD pulls them from
  GHCR on every cluster.

## 2. Finish chart migrations before handing over *(done)*

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

Each `deploy/argocd/envs/<env>/values.yaml` also sets
`appstore.secret.migration.enabled: false` explicitly, because appstore's
chart default is `true`.

## 3. Install External Secrets *(done)*

`deploy/argocd/bootstrap/external-secrets.yaml` installs ESO chart 2.13.0 into
the `external-secrets` namespace. The root Application (section 9) applies it
along with the rest of `bootstrap/`. ESO doesn't depend on anything else in
this procedure, though, so it can be applied on its own first, which lets
you connect it to Vault (section 4) before the bootstrap:

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
- no admission policy blocks ESO. List the constraints Gatekeeper enforces;
  the others only record violations. ESO's three containers are not
  privileged and set `allowPrivilegeEscalation: false`, which satisfies AKS's
  usual "no privileged containers" and "no privilege escalation" policies:

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

## 4. Connect External Secrets to Vault *(done)*

External Secrets reads Vault through one ClusterSecretStore named `vault`,
defined in `deploy/argocd/bootstrap/vault-cluster-secret-store.yaml`. Every
ExternalSecret under `deploy/argocd/envs/` points at it. It logs in with a
single Vault token for the whole cluster, kept in the Secret `vault-token` in
the `external-secrets` namespace. That Secret is created by hand and never
committed.

- The token's Vault policy only allows reading this cluster's entries on the
  `helx` mount (`helx/data/+/azure/*`).
- The store's `conditions` list the namespaces allowed to use it. Add a
  namespace there when you add an environment.
- The token lasts at most a year. `bootstrap/vault-token-renewal.yaml` renews
  it weekly, and someone replaces it once a year (below).

### Can the cluster reach Vault?

ESO runs in the cluster and connects to Vault on every refresh, so pods in the
cluster need a network path to Vault. RENCI's Vault is usually only reachable
over the VPN, so on a new cluster this has to be confirmed before anything
else in this section. Run this from a throwaway pod (it only asks Vault whether
it is up):

```sh
kubectl --context ai-sandbox -n ai-sb-test run vault-check --rm -i \
  --restart=Never --image=curlimages/curl:8.10.1 --command -- sh -c \
  'sleep 3; curl -sS --max-time 10 -o /dev/null -w "HTTP %{http_code} from %{remote_ip}\n" https://vault.apps.renci.org/v1/sys/health; echo "curl exit $?"'
```

The `sleep 3` matters. `kubectl run -i` attaches to the pod only after it has
started, and a bare `curl` finishes before that, so its output is lost and the
command prints nothing whether or not it worked.

- **`HTTP 200`, `429`, `472`, `473`, `501`, or `503`:** the cluster reached
  Vault itself; these are Vault's normal health answers (200 active, 429
  unsealed standby, 503 sealed, and so on). A standby forwards requests to
  the active node, so 429 works for ESO too. Carry on below.
- **`HTTP 403`:** the cluster reached the server, but an access rule in front
  of Vault refused the cluster's address. Ask the team that runs Vault to
  allow the cluster's outbound IP (next section).
- **`HTTP 000` with `curl exit 28` (timeout) or `curl exit 6` (could not
  resolve host):** nothing got through. `vault.apps.renci.org` resolves to a
  public address (152.54.15.132), so the usual fix is the same allow-list
  request. If they can't do that, the network administrators need to route
  the cluster's outbound traffic to Vault (for example a site-to-site VPN or
  private link from the cluster's Azure network to RENCI). Until one of these
  is done, External Secrets can't fill any Secret here.

**If the cluster can never reach Vault**, keep the secret values somewhere it
can reach instead, such as Azure Key Vault. External Secrets supports both, so
the charts would render the same ExternalSecrets and produce the same
Kubernetes Secrets, and sections 5–11 would still apply with a different
place to store the values. Only two things would change:

1. `bootstrap/vault-cluster-secret-store.yaml`: the store's `provider`
   becomes `azurekv` (Azure Key Vault, logging in with workload identity)
   instead of `vault`, and the renewal CronJob goes away. Keep the name
   `vault`, or every ExternalSecret's `secretStoreRef.name` would need
   changing as well.
2. The name each value is stored under. Every `remoteRef` and `extract.key`
   in `deploy/argocd/envs/<env>/values.yaml` and
   `manifests/postgres-secrets.yaml` is a Vault path such as
   `dev/azure/ai-sb-test/appstore/helx-appstore-secrets`. Azure Key Vault
   names can't contain `/`, so each would become something like
   `dev-azure-ai-sb-test-appstore-helx-appstore-secrets`. Each Azure Key Vault secret
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

The Azure cluster's `outboundType` is `loadBalancer`, with one outbound IP,
**9.169.134.173** (Standard SKU, so static). Its node pools don't give nodes
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
upgrades, and Kubernetes upgrades leave it alone. It changes if someone
changes the cluster's outbound settings, for
example the number of managed outbound IPs or the outbound type. If the
cluster is recreated, it gets a new address and the allow-list must be
updated. Microsoft's stop/start documentation warns only that the API
server's IP may change after `az aks start`; it doesn't mention the outbound
IP, so re-check it after a stop and start. Don't confuse it with
`pubip-ingress-nginx` in the same resource group: that is the inbound address
for the ingress controller, not the one pods' outbound traffic uses.

For an address that survives all of that, create a public IP (or prefix) yourself and attach it with
`az aks update --load-balancer-outbound-ips <id>` before asking for the
allow-list.

### Create the Vault policy and token

Run these from a machine on the VPN, logged in to Vault (`vault login`).

HeLx entries live on the KV version 2 mount `helx`, at
`<tier>/<cloud>/<namespace>/<service>/<Kubernetes Secret name>`, for example
`dev/azure/ai-sb-test/appstore/helx-postgresql` (section 5). The policy lets
the token read this cluster's entries and nothing else. KV version 2 stores
values under `<mount>/data/`, and `+` matches any one path segment, so this
covers every tier (`dev`, `prod`, ...) on the Azure cluster:

```sh
vault policy write helx-eso-read - <<'POLICY'
path "helx/data/+/azure/*" {
  capabilities = ["read"]
}
POLICY
```

`vault secrets list -detailed` shows each mount's name and KV version. If the
entries are on a different mount, change the policy path and `path:` in
`vault-cluster-secret-store.yaml` to match. A policy change applies to
existing tokens straight away, so it never needs a new token.

Create the token:

```sh
vault token create -orphan -policy=helx-eso-read -period=768h \
  -explicit-max-ttl=8760h -display-name=eso-<cluster>
```

- **`-orphan`:** without it, the new token is a child of your own login
  token, and Vault revokes it when yours expires.
- **`-period=768h`:** makes a periodic token, which lives as long as it is
  renewed within each 768h. A token made with `-ttl` instead stops at Vault's
  maximum token lifetime (768h) no matter how often it is renewed. Don't add
  `-ttl`; the period overrides it anyway.
- **`-explicit-max-ttl=8760h`:** the hard limit, one year after creation.
- **`default`:** Vault adds this policy automatically. It lets the token look
  itself up and renew itself, which the renewal job needs.

Creating a token with a policy you don't hold yourself, a period, or the
orphan flag needs `sudo` on `auth/token/create`. Check with
`vault token capabilities auth/token/create`. Without it, ask the Vault team
for a token role with `allowed_policies=helx-eso-read`, `token_period=768h`,
`token_explicit_max_ttl=8760h`, and `orphan=true`, and create the token with
`vault token create -role=<role>`.

Check the new token:

```sh
VAULT_TOKEN='<new token>' vault token lookup
```

Expect `period` `768h`, `explicit_max_ttl` `8760h`, `ttl` close to `768h`,
`renewable` `true`, `orphan` `true`, and `policies` `[default helx-eso-read]`.
A `period` of `0s` means Vault made a normal token, which would expire after
768h however often it was renewed.

Check that it can read a HeLx entry and nothing more. The first command
should print the entry (once section 5 has filled it) and the second should
fail with "permission denied":

```sh
VAULT_TOKEN='<new token>' vault kv get -mount=helx -format=json dev/azure/ai-sb-test/appstore/helx-postgresql | jq '.data.data | keys'
VAULT_TOKEN='<new token>' vault kv put -mount=helx dev/azure/ai-sb-test/test x=1
```

### Put the token in the cluster

Store the token in the Secret `vault-token`, reading it without echoing it or
leaving it in your shell history (`read` below is zsh; in bash use
`read -rsp 'Vault token: ' VAULT_ESO_TOKEN`):

```sh
read -rs 'VAULT_ESO_TOKEN?Vault token: '; echo
kubectl --context ai-sandbox -n external-secrets create secret generic vault-token \
  --from-literal=token="$VAULT_ESO_TOKEN"
unset VAULT_ESO_TOKEN
```

The `external-secrets` namespace exists once section 3 is done.

### Apply the store and the renewal job

Both files are in `bootstrap/`, so the root Application (section 9) applies
them. Applying them by hand now lets you check the connection first; the root
Application takes them over later without changing anything:

```sh
kubectl --context ai-sandbox apply -f deploy/argocd/bootstrap/vault-cluster-secret-store.yaml
kubectl --context ai-sandbox apply -f deploy/argocd/bootstrap/vault-token-renewal.yaml
```

Check that ESO can log in. `READY` must be `True`; if it isn't,
`kubectl describe clustersecretstore vault` shows Vault's error:

```sh
kubectl --context ai-sandbox get clustersecretstore vault
```

Run the renewal once by hand instead of waiting for Monday, and read its
output. It prints the new expiry and when the token was issued, never the
token itself:

```sh
kubectl --context ai-sandbox -n external-secrets create job vault-token-renewal-now \
  --from=cronjob/vault-token-renewal
kubectl --context ai-sandbox -n external-secrets wait --for=condition=complete \
  job/vault-token-renewal-now --timeout=2m
kubectl --context ai-sandbox -n external-secrets logs job/vault-token-renewal-now
kubectl --context ai-sandbox -n external-secrets delete job vault-token-renewal-now
```

If a scheduled run ever fails, `kubectl -n external-secrets get jobs` shows
it. The token has three more weekly runs before it would lapse.

### Replace the token once a year

Renewal can't extend a token past its `explicit_max_ttl`, so a year after the
token was issued it stops working. The renewal job's log prints the issue
date. Before then:

1. Create and check a new token as above.
2. Replace the Secret's contents (ESO picks up the change on its own):

   ```sh
   read -rs 'VAULT_ESO_TOKEN?Vault token: '; echo
   kubectl --context ai-sandbox -n external-secrets create secret generic vault-token \
     --from-literal=token="$VAULT_ESO_TOKEN" --dry-run=client -o yaml \
     | kubectl --context ai-sandbox apply -f -
   unset VAULT_ESO_TOKEN
   ```

3. Check `kubectl get clustersecretstore vault` is still `READY`, then revoke
   the old token: `vault token revoke '<old token>'`.

If the token does lapse, Kubernetes Secrets that ESO already created stay in
place and running apps keep working. ESO only stops picking up changes from
Vault and can't fill Secrets for anything new until the token is replaced.

### Other ways to log in

A single token is what the Vault team recommends. Vault's JWT login, or its
Kubernetes login, would avoid both the stored token and the yearly
replacement. Each namespace's ServiceAccount token would identify it to
Vault, and Vault could limit each namespace to its own entries. Those need
Vault-side setup (an auth mount and a role per namespace). Kubernetes login
also needs Vault to reach the cluster's API server. Only
`vault-cluster-secret-store.yaml` would change to use either.

## 5. Move each secret into Vault *(done)*

Every Secret that the chart used to create gets one Vault entry, on the
`helx` mount, with the same name and the same keys. Each sits under the
service that owns it, at `<tier>/<cloud>/<namespace>/<service>/<Secret name>`.
The values files in section 6 already point at these paths. For `ai-sb-test`
(tier `dev`, cloud `azure`):

| Kubernetes Secret                 | Vault entry on the `helx` mount                                | Keys |
| --------------------------------- | -------------------------------------------------------------- | ---- |
| `helx-appstore-secrets`           | `dev/azure/ai-sb-test/appstore/helx-appstore-secrets`           | `SECRET_KEY`, `APPSTORE_DJANGO_USERNAME`, `APPSTORE_DJANGO_PASSWORD`, `PG_DB_PASSWORD` |
| `pgadmin-env`                     | `dev/azure/ai-sb-test/appstore/pgadmin-env`                     | `PGADMIN_DEFAULT_PASSWORD`, `PGADMIN_DEFAULT_EMAIL`, `HELX_DB_HOSTNAME`, other `PGADMIN_*` settings |
| `helx-postgresql`                 | `dev/azure/ai-sb-test/appstore/helx-postgresql`                 | `password` (appstore's database user), `postgres-password` (admin) |
| `helx-appstore-sockets`           | `dev/azure/ai-sb-test/appstore-sockets/helx-appstore-sockets`   | `PUBLISHER_SECRET` |
| `openldap-credentials`            | `dev/azure/ai-sb-test/helx-ldap/openldap-credentials`           | `LDAP_ADMIN_PASSWORD`, `LDAP_CONFIG_ADMIN_PASSWORD` |
| `helx-ldap-sync-secrets`          | `dev/azure/ai-sb-test/ldap-sync/helx-ldap-sync-secrets`         | `SOURCE_BIND_PASSWORD`, `TARGET_BIND_PASSWORD` |
| `helx-ldap-sync-postgres`         | `dev/azure/ai-sb-test/ldap-sync/helx-ldap-sync-postgres`        | `postgres-password`, `database`, `host`, `port`, `uri`, `username` |
| `helx-user-mutator-tls`           | `dev/azure/ai-sb-test/user-mutator/helx-user-mutator-tls`       | `tls.crt`, `tls.key`, `ca.crt` |
| `helx-user-mutator-ldap-password` | `dev/azure/ai-sb-test/user-mutator/helx-user-mutator-ldap-password` | `password` |

The entries must hold these keys directly, one value per key. External
Secrets copies an entry's keys into the Kubernetes Secret exactly as they are
and doesn't read YAML, so an entry holding a Helm values file would produce a
Secret with the single key `secrets.yaml` instead of `SECRET_KEY` and the rest.

### Converting between `secrets.yaml` and Vault entries

A `secrets.yaml` for `make helm-deploy` and the Vault entries above hold the
same values in two shapes. Three Make targets convert between them, and a
fourth uploads the result, using `deploy/helm/vault-secrets-map.yaml`,
which records each Secret's service and where each of its keys lives in
the Helm values:

- **`make helm-secrets-to-vault NAMESPACE=<namespace>`** renders the chart that
  `make build-helx-chart` packaged, with your values files, for that
  namespace, and writes each
  Secret the chart would create as `<service>/<Secret name>.json` under
  `dist/vault-secrets/` (which is gitignored). It uses the files listed in
  `LOCAL_VALUES_FILE`, followed by any `VALUES=`. If `LOCAL_VALUES_FILE`
  doesn't exist or lists nothing, it uses `VALUES=` alone. It renders twice
  and refuses to write anything if a value differs between the two, listing
  the values paths to add to `secrets.yaml`. A value that differs is one the
  chart generates, which Argo CD would replace on every sync. Otherwise it
  shows the values files it used, the output folder (and whether that's the
  default `VAULT_SECRETS_DIR`), and any files it would overwrite. It then asks
  once whether to proceed (`ASSUME_YES=1` skips the question).
- **`make vault-secrets-to-helm`** turns those JSON files back into one
  combined `secrets.yaml` (`dist/vault-secrets/secrets.yaml`) for
  `make helm-deploy`. If that file already exists, it asks y/n before
  overwriting it (`ASSUME_YES=1` skips the question).
- **`make vault-secrets-from-cluster`** copies the live Secrets of a running
  release into the same JSON files. It only reads from the cluster. It is the
  only source for values the charts generated, which no `secrets.yaml` holds.
  If any file it would write already exists, it lists them and asks y/n
  before overwriting (`ASSUME_YES=1` skips the question).
- **`make vault-secrets-upload VAULT_PATH=<prefix>`** writes those JSON files
  to Vault, one entry per file at `<VAULT_PATH>/<service>/<Secret name>` on
  the `helx` mount, using the `vault` CLI. It lists every entry it will write,
  and the Vault address, then asks y/n (`ASSUME_YES=1` skips it). It stops at
  the first failure and says which entries were written. It needs `VAULT_ADDR`
  set and a `vault login`. Each upload adds a new version of an entry; KV
  version 2 keeps the earlier ones.

`VAULT_PATH` is the path prefix, on the `helx` mount, under which all of a
namespace's secrets are stored (e.g. `dev/azure/ai-sb-test` for `ai-sb-test`).
The JSON targets also print a `vault kv put` command per file, for uploading
by hand. These use `$VAULT_PATH` from your shell unless you passed
`VAULT_PATH=` to Make. Every file holds plaintext secrets and is created
readable by its owner only; `dist/` is ignored by Git. Delete the files once
they are uploaded. `make help-local-dev` lists the variables each target
takes.

### Taking over a running release

Copy the **live** values; don't make new ones. The databases were initialised
with the live passwords, and the webhook's CA bundle in `values.yaml` matches
the live certificate.

1. Copy the live Secrets to JSON:

   ```sh
   make vault-secrets-from-cluster NAMESPACE=ai-sb-test
   ```

2. Upload them, from a machine on the VPN, logged in to Vault with write
   access to `helx/dev/azure/ai-sb-test/`:

   ```sh
   export VAULT_ADDR=https://vault.apps.renci.org
   vault login
   make vault-secrets-upload VAULT_PATH=dev/azure/ai-sb-test
   ```
3. Turn the same JSON into a complete `secrets.yaml`, including the values the
   charts used to generate:

   ```sh
   make vault-secrets-to-helm
   ```

   Keep `dist/vault-secrets/secrets.yaml` wherever you keep secrets files and
   list it in `LOCAL_VALUES_FILE` in their place.
4. Check that the new `secrets.yaml` describes the same Secrets, by rendering
   it back to JSON in a second folder and comparing:

   ```sh
   make helm-secrets-to-vault NAMESPACE=ai-sb-test VAULT_SECRETS_DIR=dist/vault-secrets-check
   diff -r -x secrets.yaml dist/vault-secrets dist/vault-secrets-check
   ```

   The only expected difference is a missing final newline at the end of
   `tls.key` in `helx-user-mutator-tls.json`. When the chart builds a Secret
   from values, helx-common drops the final newline of its alphabetically last
   key. A PEM key loads the same either way.
5. Delete both folders: `rm -rf dist/vault-secrets dist/vault-secrets-check`.

### A new environment, or changing a secret later

Edit the environment's `secrets.yaml`, then run
`make helm-secrets-to-vault NAMESPACE=<namespace>`, then
`make vault-secrets-upload VAULT_PATH=<prefix>`. `NAMESPACE` is required and
is never taken from your `kubectl` context, because some values the charts
derive contain it, such as ldap-sync's database `host` and `uri`. For a new
environment, its error message lists
every value the charts would otherwise generate; add each to `secrets.yaml`.
External Secrets picks up changed entries within an hour (`refreshInterval`),
or straight away with:

```sh
kubectl -n <namespace> annotate externalsecret <name> force-sync="$(date +%s)" --overwrite
```

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

Without the third values file, these objects differ between renders:

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
`helx-user-mutator-ldap-password`) are stable under `make helm-deploy` only
because they read their values from the secrets files. Under Argo CD they move
to Vault too. With the
third values file, the two renders are identical, and the chart renders no
Secret objects at all.

The CA bundle is public, so it is committed. Read it from the live webhook:

```sh
kubectl --context ai-sandbox get mutatingwebhookconfiguration \
  helx-user-mutator-webhook-ai-sb-test \
  -o jsonpath='{.webhooks[0].clientConfig.caBundle}'
```

The one in `deploy/argocd/envs/ai-sb-test/values.yaml` is valid until
2036-10-11. When it is replaced, update the Vault entry
`helx-user-mutator-tls` and `webhook.caBundle` together.

Two other Helm features behave differently under Argo CD; neither needs a
change:

- `post-install,post-upgrade` hooks (`helx-ldap` configure Job, `ldap-sync`
  search bootstrap) become Argo CD PostSync hooks and run after **every**
  sync. Both check before changing anything, so repeating them is safe.
- `helm test` Pods are left out with `skipTests: true` in the ApplicationSet.

Compared with the Helm render, the only differences are Secrets becoming
ExternalSecrets and the webhook's `caBundle`, which matches the live one.
No Deployment or StatefulSet template changes, so the takeover itself restarts
nothing. Pods do roll when the first ACR candidate changes the image tags.

## 7. Publish a chart Argo CD can follow, and images the cluster can pull *(CI on the branch, not merged; ACR token and GitHub settings not done yet)*

### The chart: numbered candidates on GHCR

For a test environment that follows `develop`, the chart's version must
change on every push. Argo CD caches a chart by its version string, so it
never notices that the mutable `5.1.1-develop` tag on GHCR was overwritten.

So `develop.yml` publishes every candidate twice to
`oci://ghcr.io/helxplatform/helm-charts/helx`:

- `publish-candidate`: the mutable `<version>-develop`
- `publish-numbered-candidate`: the same content as
  `<version>-develop.<run number>` (for example `5.1.1-develop.214`),
  published once and never overwritten

`deploy/argocd/envs/ai-sb-test/config.yaml` follows GHCR with the version range
`>=0.0.0-0`, which means "the newest version, prereleases included". Run
numbers compare as numbers, so `develop.10` sorts above `develop.9`, and
raising the umbrella version (`5.2.0-develop.1`) sorts above every
`5.1.1-develop.*`.

The range also matches releases. Right after a release such as `5.1.1` is
cut, that release is the newest version until the first `develop` push with a
higher umbrella version, so the test environment runs it. That is
intentional, and it is why released images are copied to ACR too (below).
CI publishes and copies released images only as `v<appVersion>`, so every
chart's default image tag must be `v<appVersion>` as well, or a release names
an image that isn't there.

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

Images this repository doesn't build are set separately in the same file:
Bitnami PostgreSQL, os-shell, openresty, and unc-group-x point at ACR. ldap-sync's `docker.io/postgres` and pod-reaper's
`helxplatform/pod-reaper` come from Docker Hub, which this cluster can reach.

To set it up (someone with ACR and GitHub admin rights), with `az` logged in
to the registry's subscription:

1. Check that GitHub-hosted runners can reach the registry, and that the
   token doesn't exist yet. These commands only read:

   ```sh
   ACR=aisandboxrencitgt
   az acr show -n "$ACR" --query \
     '{sku: sku.name, publicNetworkAccess: publicNetworkAccess, defaultAction: networkRuleSet.defaultAction}'
   az acr token list -r "$ACR" --query '[].name'
   ```

   `publicNetworkAccess` must be `Enabled`, and `defaultAction` `Allow` or
   `null`. A registry that denies by default or is private-only can't take
   pushes from GitHub's runners; it needs a self-hosted runner inside its
   network instead. Tokens work on every SKU.

2. Create a token CI can push with, limited to `helxplatform/`. A wildcard
   must be a single `/*` at the end of the path, and it also covers
   repositories that don't exist yet, so a new image needs no change here.
   `--no-passwords` keeps `az` from printing a password; the next step makes
   one:

   ```sh
   az acr scope-map create -r "$ACR" -n helx-ci-push \
     --description 'HeLx CI: copy images from Harbor' \
     --repository 'helxplatform/*' content/read content/write
   az acr token create -r "$ACR" -n helx-ci --scope-map helx-ci-push --no-passwords
   ```

   Check it: `status` must be `enabled`, and the scope map's actions must be
   `content/read` and `content/write` on `helxplatform/*` only:

   ```sh
   az acr token show -r "$ACR" -n helx-ci --query '{status: status, scopeMap: scopeMapId}'
   az acr scope-map show -r "$ACR" -n helx-ci-push --query actions
   ```

3. Generate the token's password straight into the clipboard, so it never
   appears in the terminal (`pbcopy` is macOS; on Linux pipe to
   `xclip -selection clipboard`):

   ```sh
   az acr token credential generate -r "$ACR" -n helx-ci --password1 \
     --expiration-in-days 365 --query 'passwords[0].value' -o tsv | pbcopy
   ```

   Without `--expiration-in-days` the password never expires. With it, the
   mirror jobs start failing once it lapses; replace it before then (below).

4. In the GitHub repository settings (Settings → Secrets and variables →
   Actions), add the secret `ACR_PASSWORD` by pasting the clipboard, then the
   secret `ACR_USERNAME` (the token name, `helx-ci`), then the variable
   `ACR_LOGIN_SERVER=aisandboxrencitgt.azurecr.io`. Add the variable last:
   it is what turns the mirror jobs on, so a push in between would run them
   without credentials. Clear the clipboard afterwards.

5. Get every image into ACR before Argo CD is bootstrapped: push to `develop`
   (or run "Develop channel" from the Actions tab) for the candidate images,
   and let the next push to `main` copy the released ones. Until then, a
   numbered candidate published before the variable was set names images
   that are not in ACR. Check that the copies arrived; each built image should
   show a `develop-<sha>` tag (and, after a release, `v<appVersion>`):

   ```sh
   az acr repository show-tags -n "$ACR" --repository helxplatform/appstore \
     --orderby time_desc --top 3
   ```

To replace the password, generate the other one (`--password2` in step 3),
update `ACR_PASSWORD` with it, wait for a `develop` run to pass, then delete
the old one with `az acr token credential delete -r "$ACR" -n helx-ci
--password1`. The two passwords take turns.

## 8. Give Argo CD access to the repositories *(not done yet)*

- **GitHub** (`https://github.com/helxplatform/helx.git`) is public, so it
  needs no credentials.
- **GHCR** (`ghcr.io/helxplatform/helm-charts`) serves charts without
  credentials but refuses to list tags anonymously, and Argo CD lists tags to
  resolve the `>=0.0.0-0` range. Register it with a GitHub token that
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

- `kubectl get clustersecretstore vault` shows `READY` `True` (section 4)
- every Vault entry exists (section 5)
- the images are in ACR (section 7)
- the GHCR repository Secret exists (section 8)

The bootstrap reads `develop`, so `deploy/argocd/` and the env's values must
be merged there first. To try it from a branch before merging, change
`targetRevision` in `root.yaml`,
`revision` in `bootstrap/applicationset-helx.yaml`, and `valuesRef` in the
env's `config.yaml` to the branch, and change them back before merging.

```sh
kubectl --context ai-sandbox apply -n argocd -f deploy/argocd/root.yaml
```

Then check that `root`, `external-secrets`, and `helx-ai-sb-test` exist, and
that `root` and `external-secrets` are Synced:

```sh
kubectl --context ai-sandbox -n argocd get applications
```

If External Secrets, the ClusterSecretStore, and the renewal CronJob were
applied by hand in sections 3 and 4, `root` takes them over without changing
them.

`helx-ai-sb-test` starts with automatic sync off (`autoSync: false`), so
nothing in `ai-sb-test` changes until someone presses Sync.

## 10. Take over the existing Helm release *(not done yet)*

Argo CD takes over a Helm release by applying the same objects under the same
names: same release name (`releaseName: helx`), same namespace. It adds its
tracking annotation to each object on the first sync. Helm's own release
record (`sh.helm.release.v1.helx.*` Secrets) is not touched.

1. In the Argo CD UI, open `helx-ai-sb-test` and press **App Diff**. Expect:
   - image tags changing from whatever the release was last deployed with
     to `develop-<sha>`
   - ExternalSecrets being added
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
   and sets `valuesRef: main`), and the Vault paths and CA bundle in
   `values.yaml` and `manifests/`.
3. Add the namespace to `destinations` in `bootstrap/project-helx.yaml` and
   to `conditions` in `bootstrap/vault-cluster-secret-store.yaml`.
4. Re-run the double render from section 6 for the new values files.
5. Section 5 for its Vault entries (the token's policy already covers every
   `helx/` path), then 10 and 11.

On a new cluster, Argo CD itself and section 8 come first, then sections 3
and 4 (External Secrets, and a new Vault token in that cluster's
`vault-token` Secret), then `root.yaml` (section 9). A cluster that pulls from Harbor needs no ACR steps and no
repository overrides in its values; one that can't pull from Harbor needs its
own copy of section 7's ACR setup, since the CI jobs copy to a single registry.
