# user-mutator Helm chart

Chart `1.7.0` uses the `helx-common` `0.1.1` library for its webhook TLS and optional LDAP password Secret contracts.

## Secret modes

Each known contract supports exactly one of these ownership modes:

1. **Existing Secret** (backward-compatible default): leave `existingSecret` set to the historical resource name. The chart references the Secret but does not manage it.
2. **Chart-managed Secret**: set `existingSecret: ""` and supply plaintext entries under `values`. Persisted target data is retained on upgrades. Historical Secrets are caller-owned and are not adopted automatically.
3. **External Secrets Operator**: set `existingSecret: ""`, enable `externalSecret.enabled`, and configure `remoteRef` plus `secretStoreRef`. `existingSecret` and ExternalSecret mode are mutually exclusive.

### Webhook TLS

The top-level `secret` contract defaults to the existing `user-mutator-cert-tls` Secret. Managed and default ESO modes target `<fullname>-tls` with type `kubernetes.io/tls`. Keys `tls.crt` and `tls.key` are required; `ca.crt` is optional.

```yaml
secret:
  existingSecret: ""
  values:
    tls.crt: replace-me
    tls.key: replace-me
    # ca.crt: optional
```

### LDAP password

The `ldap.secret` contract is rendered and mounted only when `config.features.ldap` is enabled. It defaults to the existing `user-mutator-ldap-password` Secret; chart managed and default ESO modes target `<fullname>-ldap-password` and require the `password` key.

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
    existingSecret: ""
    values:
      password: replace-me
```

## Additional caller-managed Secrets

Use `config.additionalSecrets` only for unknown extra contracts. Its keys become entries in the generated `config.json` `secrets` map and mount paths under `/etc/user-mutator-secrets/<key>`; values are existing Kubernetes Secret names. The known aliases `cert` and `ldap-password` are reserved and cause rendering to fail if overridden.

```yaml
config:
  additionalSecrets:
    extra-credentials: caller-managed-secret
```

## Deprecated: `config.secrets`

`config.secrets` still works and continues to render exactly as it did before. It is deprecated, and support will be removed in the next major version.

It is resolved per alias, and only where the caller has not chosen one of the three modes above:

| Alias | Behaviour when `config.secrets` supplies it |
| --- | --- |
| `cert` | Used when `secret` is untouched, meaning `existingSecret` still holds `user-mutator-cert-tls`, `values` is empty, and `externalSecret.enabled` is false. |
| `ldap-password` | Used when `ldap.secret` is untouched, meaning `existingSecret` still holds `user-mutator-ldap-password`, `values` is empty, and `externalSecret.enabled` is false. Only applies when `config.features.ldap` is enabled. |
| anything else | Treated exactly as a `config.additionalSecrets` entry. |

Supplying a legacy alias *and* configuring the matching contract is a contradiction, so rendering fails with a message naming the alias rather than silently picking a winner. Resolve it by deleting the `config.secrets` entry.

`config.secrets` is intentionally absent from `values.yaml`. That absence is what lets the chart distinguish a caller-supplied map from a chart default; re-adding it would break the deprecation path.

To migrate, move the `cert` entry to `secret.existingSecret`, the `ldap-password` entry to `ldap.secret.existingSecret`, and everything else to `config.additionalSecrets`.

The committed `Chart.lock` pins the exact `helx-common` dependency used by this chart.
