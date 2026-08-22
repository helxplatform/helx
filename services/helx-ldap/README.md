# helx-ldap

This service provides the HeLx LDAP deployment and the tools used to administer
LDAP users and groups.

## Repository layout

- `chart/` is the Helm wrapper chart. It wraps the pinned
  `openldap-stack-ha` dependency and applies the HeLx-specific LDAP
  configuration as a Helm hook.
- `scripts/` contains optional Python administration utilities for querying and
  changing LDAP users, groups, and entries.
- `test/users.yaml` contains sample input for the user-management scripts.

The LDIF files used during deployment are packaged under
`chart/files/ldif/`. The chart is now the source of truth for the deployment
configuration.

## Deploying LDAP

The recommended deployment is through the umbrella chart in
`deploy/helm/helx-chart`. The target Kubernetes namespace must already exist;
the smoke-test script does not create namespaces.

From the repository root:

```sh
NAMESPACE=ai-sb-test

helm registry login ghcr.io
export LDAP_ADMIN_PASSWORD='choose-an-admin-password'
export LDAP_CONFIG_ADMIN_PASSWORD='choose-a-config-password'

bash deploy/helm/helx-chart/examples/ldap-test.sh "$NAMESPACE" helx
```

The script exercises the backward-compatible existing-Secret mode: it creates
or updates `openldap-credentials`, prepares the Helm dependencies, installs only
the `helx-ldap` service, and waits for the OpenLDAP StatefulSet and configuration
hook. The same configuration Job runs on upgrades.

The selected Secret must contain these keys:

- `LDAP_ADMIN_PASSWORD`
- `LDAP_CONFIG_ADMIN_PASSWORD`

The chart also supports chart-managed `secret.values` and an ESO-managed target
through `secret.externalSecret`. ESO backed by Vault is recommended for GitOps;
do not commit plaintext credentials. See `chart/README.md` for all three modes
and the upstream chart's Secret-name constraint.

## What the wrapper chart configures

The wrapper chart deploys the pinned `openldap-stack-ha` chart and applies the
following HeLx-specific configuration in a hardened
`post-install,post-upgrade` Job:

1. Loads and enables the `memberOf` module and overlay.
2. Applies the configured anonymous-access ACL when enabled.
3. Installs the `helxUser` schema, including:
   - `runAsUser`
   - `runAsGroup`
   - `fsGroup`
   - `supplementalGroups`
   - `userAlias`

The Job waits for LDAP readiness, discovers the generated MDB database DN and
schema DN, and is idempotent across upgrades. Existing installations with the
former `kubernetesSC` schema must be migrated explicitly because the old and
new object classes use the same OID.

The chart defaults preserve the current `develop` branch behavior, including:

```yaml
openldap:
  env:
    LDAP_ALLOW_ANON_BINDING: "yes"

configuration:
  anonymousAccess:
    enabled: true
```

This is security-sensitive: the bundled anonymous ACL permits anonymous reads
of `userPassword` hashes. Treat that as a compatibility default, not a
production security baseline. For a fresh hardened deployment, use:

```yaml
helx-ldap:
  openldap:
    env:
      LDAP_ALLOW_ANON_BINDING: "no"
  configuration:
    anonymousAccess:
      enabled: false
```

Disabling the setting after the permissive ACL has already been applied does
not currently remove that ACL; existing installations require an explicit ACL
migration.

For custom LDAP naming contexts, configure `openldap.global.ldapDomain`, or
set `configuration.baseDN` and `configuration.adminDN` explicitly. The
configuration Job uses the OpenLDAP dependency image by default, which must
contain `/bin/sh`, `awk`, `sed`, `grep`, `ldapsearch`, and `ldapmodify`.

## Chart development

From the repository root:

```sh
make -C services/helx-ldap chart_dependencies
make -C services/helx-ldap chart_lint

# Only when intentionally changing dependency versions:
make -C services/helx-ldap chart_update_dependencies
```

Equivalent direct commands are:

```sh
helm dependency build services/helx-ldap/chart
helm lint services/helx-ldap/chart --with-subcharts

# Only when intentionally changing dependency versions:
helm dependency update services/helx-ldap/chart
```

The umbrella chart's LDAP-only render can be checked with:

```sh
helm template helx deploy/helm/helx-chart \
  --namespace ai-sb-test \
  --values deploy/helm/helx-chart/examples/ldap-test-values.yaml
```

## Accessing LDAP

Forward the LDAP service to a local port:

```sh
kubectl -n ai-sb-test port-forward svc/openldap 5389:389
```

The administration scripts use `ldap3` and are not part of the Helm install.
Install their Python dependencies when needed:

```sh
python3 -m pip install -r services/helx-ldap/requirements.txt
```

Most administration scripts accept connection arguments such as
`--ldap-server`, `--bind-dn`, and `--bind-password`; several also support a
user-supplied YAML configuration file through `--config`. Run a script with
`--help` to see its exact interface. The repository no longer generates an
administration configuration file, so provide connection details explicitly
or maintain that local file outside version control.

Examples, run from `services/helx-ldap` after port-forwarding:

```sh
python scripts/get_ldap_dn.py \
  --ldap-server ldap://127.0.0.1:5389 \
  --bind-dn 'cn=admin,dc=example,dc=org' \
  --bind-password '<password>' \
  --search-base 'dc=example,dc=org'

python scripts/get_ldap_users.py \
  --ldap-server ldap://127.0.0.1:5389 \
  --bind-dn 'cn=admin,dc=example,dc=org' \
  --bind-password '<password>' \
  --output-format yaml

python scripts/set_ldap_users.py test/users.yaml \
  --ldap-server ldap://127.0.0.1:5389 \
  --bind-dn 'cn=admin,dc=example,dc=org' \
  --bind-password '<password>' \
  --user-base 'ou=users,dc=example,dc=org' \
  --group-base 'ou=groups,dc=example,dc=org'
```

Use caution with administration and deletion scripts; they modify or remove
LDAP entries.
