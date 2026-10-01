# helx-ldap

This service provides the HeLx LDAP service and the tools used to administer
HeLx LDAP users and groups.

## Repository layout

- `chart/` is the Helm wrapper chart. It wraps the pinned
  `openldap-stack-ha` dependency and applies the HeLx-specific configuration
  for the HeLx LDAP service as a Helm hook.
- `scripts/` contains optional Python administration utilities for querying and
  changing HeLx LDAP users, groups, and entries.
- `test/users.yaml` contains sample input for the user-management scripts.

The LDIF files used during deployment are packaged under
`chart/files/ldif/`. The chart is now the source of truth for the deployment
configuration.

## Deploying HeLx LDAP

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

The script uses a caller-managed credentials Secret: it creates or updates
`openldap-credentials`, prepares the Helm dependencies, installs only the
`helx-ldap` service, and waits for the HeLx LDAP StatefulSet and configuration
hook. The same configuration Job runs on upgrades.

The selected Secret must contain these keys:

- `LDAP_ADMIN_PASSWORD`
- `LDAP_CONFIG_ADMIN_PASSWORD`

Choose the credentials Secret owner with `secret.mode`: `values` creates a
chart-managed Secret from `secret.values`, `existingSecret` uses a Secret you
manage, and `externalSecret` creates an ExternalSecret resource. ESO backed by
Vault is recommended for GitOps; do not commit plaintext credentials. See
`chart/README.md` for the complete configuration and the upstream chart's
Secret-name constraint.

## Migrating an existing release

The wrapper exposes the upstream chart's explicit PVC adoption path. First back
up the HeLx LDAP volume and verify the live names; with the current stable fullname,
the generated PVC is normally `data-openldap-0`:

```sh
kubectl -n "$NAMESPACE" get statefulset,pvc,secret
kubectl -n "$NAMESPACE" get pvc data-legacy-statefulset-0 -o yaml
```

Use the same Helm release name for the upgrade and provide values like these:

```yaml
helx-ldap:
  openldap:
    migration:
      enabled: true
      legacyPvc: "data-legacy-statefulset-0"
      # Only needed when automatic label discovery finds more than one
      # StatefulSet belonging to this release.
      legacyStatefulSet: ""
    persistence:
      existingClaim: "data-legacy-statefulset-0"
  secret:
    mode: existingSecret
    existingSecret: openldap-credentials
    migration:
      enabled: true
      legacySecret: "legacy-credentials-secret"
```

When `openldap.migration.enabled` is true, the `helx-ldap` pre-upgrade hook
checks that the PVC is `Bound`, discovers the prior HeLx LDAP StatefulSet for
the same Helm release, scales it to zero, waits for its pod to terminate, and
deletes only the old StatefulSet object with orphan propagation. The PVC and
its backing volume are not copied or deleted, so no manual scale-down step is
required. Set `legacyStatefulSet` explicitly if the prior StatefulSet does not
carry the expected OpenLDAP labels or if discovery finds multiple candidates.

Set `secret.migration.enabled` only when the old credentials Secret is not
already `openldap-credentials`; otherwise leave that flag disabled. The
pre-upgrade Secret hook copies `LDAP_ADMIN_PASSWORD` and
`LDAP_CONFIG_ADMIN_PASSWORD` (and any other data keys) into the target without
deleting the old Secret. It requires a live `helm upgrade` because it uses
`lookup`; it is not an Argo CD/client-side render operation.

This automated handoff is intentionally opt-in and destructive to the old
StatefulSet controller: if a later part of the upgrade fails, Helm cannot
recreate that old controller, and `--atomic` cannot undo the hook. Back up the
HeLx LDAP volume first and use a maintenance window. After a successful
migration, set both migration flags to `false`, but keep
`openldap.persistence.existingClaim` set so future upgrades continue using the
adopted PVC. Verify the PVC UID and the new StatefulSet's direct `claimName`
before considering the migration complete.

## What the helx-ldap wrapper configures

The wrapper chart deploys the pinned `openldap-stack-ha` chart and applies the
HeLx-specific `cn=config` customizations that a stock OpenLDAP deployment does
not have. They are applied by the configuration Job rendered from
`chart/templates/configure-job.yaml` and named
`<release>-helx-ldap-configure` (`helx-helx-ldap-configure` under the umbrella
chart's default release name). It is a hardened Helm
`post-install,post-upgrade` hook Job that runs the `configure.sh` script from
the `-configure` ConfigMap against `ldap://openldap:389`, binding as the
cn=config administrator (`configuration.configDN`, default
`cn=admin,cn=config`) with the password mounted from the credentials Secret.
The Job:

1. Waits for the LDAP Service to answer queries (up to 300 seconds), then
   discovers the MDB database DN below `cn=config` instead of assuming the
   upstream chart generates `olcDatabase={2}mdb`.
2. Loads the `memberOf` module and installs the `memberOf` overlay on the
   discovered database, so OpenLDAP maintains reverse `memberOf` attributes
   and group membership can be queried from the user side.
3. Writes the ACL set selected by `configuration.anonymousAccess.enabled` to
   the database's `olcAccess`, replacing it if it differs.
4. Installs the `helxUser` schema, including:
   - `runAsUser`
   - `runAsGroup`
   - `fsGroup`
   - `supplementalGroups`
   - `userAlias`

   These attributes are how HeLx stores each user's pod security context
   (run-as IDs) directly in the LDAP entry.

Every step is idempotent: each piece is checked with `ldapsearch` and skipped
when already installed, so the Job is safe to rerun on every upgrade. The Job
refuses to run when the legacy `kubernetesSC` schema is installed (it uses the
same OID as `helxUser` and must be migrated explicitly first) or when the
`helxUser` schema is only partially installed, since re-adding attributes
would create duplicates. Under the umbrella chart the Job carries hook weight
10 so it finishes before the `ldap-sync` search bootstrap Job (weight 20)
registers its search. The Job is deleted after a successful run
(`helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded`); set
`configuration.enabled: false` to manage the LDAP configuration manually.

The chart defaults preserve the current `develop` branch behavior, including:

```yaml
openldap:
  env:
    LDAP_ALLOW_ANON_BINDING: "yes"

configuration:
  anonymousAccess:
    enabled: true
```

With `anonymousAccess.enabled: true`, anonymous clients can read the POSIX
user and group entries under `ou=users` and `ou=groups`. The user-mutator
nslcd sidecar depends on this because it binds anonymously. Anonymous clients
can never read `userPassword` or `shadowLastChange`. They may only use
`userPassword` to authenticate a simple bind. With
`anonymousAccess.enabled: false`, only authenticated clients can read those
entries.

On every install and upgrade, the Job compares the database's live
`olcAccess` with the selected rule set and replaces it if they differ. So an
upgrade fixes installations that got the earlier ACL, which let anonymous
clients read password hashes. Switching the setting also takes effect on
existing installations. Hand-edited ACLs on that database are overwritten.

To refuse anonymous access entirely, use the setting below. The user-mutator
LDAP configuration has no bind DN, so user and group lookups in user app pods
stop working with it:

```yaml
helx-ldap:
  openldap:
    env:
      LDAP_ALLOW_ANON_BINDING: "no"
  configuration:
    anonymousAccess:
      enabled: false
```

For custom HeLx LDAP naming contexts, configure `openldap.global.ldapDomain`, or
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

The umbrella chart's HeLx LDAP-only render can be checked with:

```sh
helm template helx deploy/helm/helx-chart \
  --namespace ai-sb-test \
  --values deploy/helm/helx-chart/examples/ldap-test-values.yaml
```

## Accessing HeLx LDAP

Forward the `helx-ldap` service to a local port:

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
HeLx LDAP entries.
