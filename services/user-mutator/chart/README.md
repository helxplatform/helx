# user-mutator Helm chart

Chart `2.0.0` uses the `helx-common` `0.1.1` library for its webhook TLS and optional LDAP password Secret contracts.

## Secret modes

Each known contract supports exactly one of these ownership modes:

0. **Chart-generated** (webhook TLS only, and the default): the chart generates the CA and serving certificate. See below.
1. **Existing Secret**: set `existingSecret` to the Secret's name. The chart references it but does not manage it.
2. **Chart-managed Secret**: set `existingSecret: ""` and supply plaintext entries under `values`. Persisted target data is retained on upgrades. Historical Secrets are caller-owned and are not adopted automatically.
3. **External Secrets Operator**: set `existingSecret: ""`, enable `externalSecret.enabled`, and configure `remoteRef` plus `secretStoreRef`. `existingSecret` and ExternalSecret mode are mutually exclusive.

### Webhook TLS

The top-level `secret` contract defaults to `generate`, described below. Managed, ESO, and generated modes target `<fullname>-tls` with type `kubernetes.io/tls`. Keys `tls.crt` and `tls.key` are required; `ca.crt` is optional. The historical Secret name was `user-mutator-cert-tls`; set `secret.existingSecret` to keep referencing it.

```yaml
secret:
  existingSecret: ""
  values:
    tls.crt: replace-me
    tls.key: replace-me
    # ca.crt: optional
```

### LDAP password

The `ldap.secret` contract is rendered and mounted only when `config.features.ldap` is enabled. Managed and default ESO modes target `<fullname>-ldap-password` and require the `password` key. Enabling LDAP without selecting a mode fails to render, since there is then no source for the password. To keep a Secret preserved from an earlier deployment, name it in `existingSecret`; the historical name was `user-mutator-ldap-password`.

```yaml
config:
  features:
    ldap:
      host: ldap.example.org
      port: 389
      username: cn=admin,dc=example,dc=org
      user_base_dn: ou=users,dc=example,dc=org
      group_base_dn: ou=groups,dc=example,dc=org
ldap:
  secret:
    # either name a Secret you already have...
    existingSecret: user-mutator-ldap-password
    # ...or let the chart build one
    values:
      password: replace-me
```

## Webhook TLS and the MutatingWebhookConfiguration

A mutating webhook needs three things beyond the workload: a serving certificate, a `MutatingWebhookConfiguration` carrying the CA that signed it, and a way to select which namespaces are mutated. **As of chart `2.0.0` the chart renders all three by default**, so `helm install` produces a working webhook and no `make` target has to run out of band.

To manage the certificate and the configuration yourself instead, opt out explicitly:

```yaml
secret:
  generate:
    enabled: false
webhook:
  enabled: false
```

Turning `secret.generate.enabled` off leaves the three ordinary ownership modes, so name the Secret you want in `secret.existingSecret`, supply `secret.values`, or enable `secret.externalSecret`. There is no implicit fallback to a historical name.

### Certificate lifecycle

`secret.generate` is a fourth ownership mode alongside `existingSecret`, `values`, and `externalSecret`, is mutually exclusive with all three, and is the default. The chart generates a self-signed CA and a serving certificate whose SANs cover `<fullname>`, `<fullname>.<namespace>`, `<fullname>.<namespace>.svc`, and `<fullname>.<namespace>.svc.cluster.local`.

Generated material is looked up and reused on every render, so upgrades never rotate the certificate out from under a webhook configuration that already carries the matching CA bundle. The Secret also carries `helm.sh/resource-policy: keep`, so it survives an uninstall and is picked back up by a reinstall. To rotate deliberately, delete the Secret named `<fullname>-tls` and upgrade.

There is no automatic rotation, so `secret.generate.validityDays` defaults to ten years.

The Secret and the configuration are rendered from a single template file. Helm templates are pure functions with no memoisation, so resolving the certificate in two files would generate two unrelated key pairs on a fresh install and the CA bundle would not match the serving certificate.

`lookup` returns nothing during `helm template`, `helm lint`, and client-side dry runs, so rendering the chart offline twice produces two different certificates. That output is only ever inspected, never applied.

To render the configuration against a certificate the chart does not manage, leave `secret.generate.enabled` false and set `webhook.caBundle` to the base64 CA that signed it. Rendering fails if `webhook.enabled` is set with no CA bundle available from either source.

### Namespace selection

Namespaces are selected by the `kubernetes.io/metadata.name` label, which Kubernetes applies to every namespace automatically. **Nothing has to be labelled for mutation to take effect**, and the chart needs no permission to patch namespaces. `webhook.namespaces` defaults to the release namespace.

`webhook.extraMatchExpressions` is ANDed with that clause and defaults to keeping the webhook away from control-plane and AKS-managed namespaces. To restore the historical opt-in label as a per-namespace toggle, add it to `webhook.matchLabels`:

```yaml
webhook:
  matchLabels:
    enable-user-mutator-webhook-ai-sb-test: "true"
```

### Adopting a configuration created out of band

The configuration is cluster-scoped, so `webhook.name` defaults to `<fullname>-<namespace>` to keep two releases in one cluster from colliding. Set it explicitly to match an existing name.

Helm will refuse to take over an object it does not own. Either delete the old configuration before installing, or label it for adoption first:

```sh
kubectl annotate mutatingwebhookconfiguration "$NAME" \
  meta.helm.sh/release-name="$RELEASE" meta.helm.sh/release-namespace="$NAMESPACE" --overwrite
kubectl label mutatingwebhookconfiguration "$NAME" app.kubernetes.io/managed-by=Helm --overwrite
```

Installing the chart requires cluster-level permission on `admissionregistration.k8s.io`, since that is where the configuration lives.

## Additional caller-managed Secrets

Use `config.additionalSecrets` only for unknown extra contracts. Its keys become entries in the generated `config.json` `secrets` map and mount paths under `/etc/user-mutator-secrets/<key>`; values are existing Kubernetes Secret names. The known aliases `cert` and `ldap-password` are reserved and cause rendering to fail if overridden.

```yaml
config:
  additionalSecrets:
    extra-credentials: caller-managed-secret
```

## Removed: `config.secrets`

`config.secrets` was removed in chart `2.0.0`. Supplying it fails to render, naming the values to move it to. Rendering fails rather than ignoring the map because silently dropping a custom Secret name would leave the webhook serving a certificate the caller never chose.

| Old entry | Replacement |
| --- | --- |
| `config.secrets.cert` | `secret.existingSecret` |
| `config.secrets.ldap-password` | `ldap.secret.existingSecret` |
| anything else | `config.additionalSecrets` |

`config.secrets` is intentionally absent from `values.yaml`; that absence is what lets the chart tell a caller-supplied map from a chart default, so re-adding it would break the check.

The committed `Chart.lock` pins the exact `helx-common` dependency used by this chart.
