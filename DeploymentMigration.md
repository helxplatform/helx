# Deployment migration

This document describes migrations from older Helm deployments to the current
HeLx umbrella chart. It separates required migration conditions from recommended
preparation and verification steps.

## Appstore

This procedure covers upgrading an existing appstore Helm release to the current
appstore chart, either as a standalone chart or as the `appstore` dependency of
`deploy/helm/helx-chart`. It is intended to preserve the appstore database,
application credentials, Django signing key, and the existing pgAdmin
credentials.

The supported automatic path is a same-release Helm upgrade. It is not a second
installation followed by a cutover.

### Required conditions

The following conditions must be true before using the automatic migration path:

1. **The old deployment must be a Helm release.** The migration uses Helm's
   cluster-aware `lookup` function while rendering an upgrade. It does not
   discover old Secrets during a fresh install.
2. **The namespace and Helm release name must remain unchanged.**
3. **The old appstore primary Secret must still exist.** The old chart normally
   created a Secret named `<appstore-fullname>`. The current chart creates and
   consumes a managed Secret normally named `<appstore-fullname>-secrets` (the
   fullname is truncated before the `-secrets` suffix when necessary).
4. **The PostgreSQL data PVC must be identified and `Bound` when PostgreSQL is
   enabled.** Set `appstore.postgresql.persistence.existingClaim` to the exact
   existing claim name, normally `appstore-postgresql-pvc`, and verify its UID
   before and after the upgrade. Preserve the live database name, username, and
   password. In particular, the migrated `PG_DB_PASSWORD` must continue to match
   the password of the existing appstore database user.
5. **The required appstore credentials must be present or supplied as fallbacks.**
   In chart-managed mode the final Secret must contain non-empty:
   `SECRET_KEY`, `APPSTORE_DJANGO_USERNAME`, and
   `APPSTORE_DJANGO_PASSWORD`. It must also contain `PG_DB_PASSWORD` when
   `appstore.postgresql.enabled` is true. The old primary Secret is authoritative
   during the first migration; values only fill keys missing from persisted data.

### Secret migration behavior

Leave the appstore Secret settings in chart-managed mode for the first automatic
migration:

```yaml
appstore:
  enabled: true
  secret:
    existingSecret: ""
    migration:
      enabled: true
    externalSecret:
      enabled: false
    values:
      # Only needed for keys absent from the persisted Secret. Do not use these
      # entries to rotate credentials during the migration.
      SECRET_KEY: "<only-if-the-legacy-key-is-missing>"
      APPSTORE_DJANGO_USERNAME: "<only-if-the-legacy-key-is-missing>"
      APPSTORE_DJANGO_PASSWORD: "<only-if-the-legacy-key-is-missing>"
      PG_DB_PASSWORD: "<must-match-the-live-database-password-if-needed>"
```

The `secret.existingSecret` and `secret.externalSecret.enabled` modes are
mutually exclusive with chart-managed mode. They are valid alternatives, but
neither mode performs the legacy Secret lookup or key normalization:

- **Chart-managed migration:** leave both external ownership settings disabled.
  The chart looks up `<appstore-fullname>` as the legacy Secret and writes the
  preserved data to `<appstore-fullname>-secrets`. On the first migration, the
  legacy Secret is authoritative. On later upgrades, a target marked with
  `appstore.helxplatform.io/migrated-from: <appstore-fullname>` is canonical and
  the legacy Secret only fills missing keys.
- **Caller-managed Secret:** set `appstore.secret.existingSecret` to a Secret
  that already contains the current key names and all required credentials. Do
  not simply point it at an old primary Secret that contains only
  `APPSTORE_SECRET_KEY`; the caller-managed path does not rename that key to
  `SECRET_KEY`. If the old Secret is the intended source, copy its data to a
  new caller-managed Secret and add the modern key before the upgrade.
- **External Secrets:** populate the remote backend with the current key names,
  especially `SECRET_KEY`, and configure
  `appstore.secret.externalSecret`. The target Secret must be available in the
  namespace before the appstore pod starts. External Secrets mode is not a
  substitute for migrating the old primary Secret automatically; transfer and
  verify the old values in the backend first.

For chart-managed mode, the old `APPSTORE_SECRET_KEY` is normalized to the
current `SECRET_KEY` automatically. This applies to persisted migration data and
to `appstore.secret.values`; use `SECRET_KEY` in new configuration anyway. The
computed database settings `PG_DB_ENGINE`, `PG_DB_DATABASE`, `PG_DB_USERNAME`,
`PG_DB_HOST`, `PG_DB_PORT`, and `POSTGRES_ENABLED` are injected directly by the
Deployment and should not be added to the appstore Secret. `PG_DB_PASSWORD`
remains Secret-backed.

Values supplied in `appstore.secret.values` are fallback values only. If a key
already exists in the target or legacy Secret, changing that value in Helm
values does not rotate it. Rotate credentials directly in the canonical Secret
through the chosen Secret-management process, and account for any database or
Django restart required by that rotation.

### The `pgadmin-env` case

`pgadmin-env` is a separate, fixed-name Secret; it is not the appstore primary
Secret and must not be configured as `appstore.secret.existingSecret`. When
`appstore.pgadmin.enabled` is true, the current `pgadmin-secrets.yaml` renders
it through the shared Secret helper with `pgadmin-env` as its exact target name.

On an upgrade, the helper looks up the existing `pgadmin-env` Secret and treats
its data as canonical. The generated values in the chart are only fallbacks for
keys that are absent. This specifically preserves the existing
`PGADMIN_DEFAULT_PASSWORD` and avoids replacing the old pgAdmin password with a
new random value. Keep `pgadmin-env` in the namespace and verify that
`PGADMIN_DEFAULT_PASSWORD` exists before upgrading. Do not delete or rename it
as part of the appstore primary Secret migration.

This behavior is independent of `appstore.secret.migration.enabled`; the
`pgadmin-env` lookup is handled by its own template. If values such as
`apps.PGADMIN_EMAIL` or `apps.HELX_DB_HOSTNAME` need to change after migration,
remember that existing Secret keys take precedence over those generated
fallbacks. Change the canonical `pgadmin-env` Secret deliberately rather than
expecting a Helm values change to overwrite it.

The chart also renders other auxiliary Secrets, including `atlas-env`,
`imagej-env`, `octave-env`, `webtop-env`, and `webtop-pgadmin-env`. They are not
part of the appstore primary Secret migration. In particular, the current
`imagej-env` and `octave-env` templates still generate random `VNC_PW` values;
this procedure does not guarantee preservation of those values. Inventory any
enabled auxiliary service and arrange separate Secret ownership or migration if
its existing credential must remain unchanged.

### Preparation and values review

Before upgrading:

- Record the live release, namespace, rendered appstore fullname, Secret names,
  PVC names, and PVC UIDs. The exact names are more reliable than assumptions
  based on defaults:

  ```sh
  export RELEASE="your-release"
  export NAMESPACE="your-namespace"
  helm get values "$RELEASE" --namespace "$NAMESPACE" --all > /secure/path/old-values.yaml
  helm get manifest "$RELEASE" --namespace "$NAMESPACE" > /secure/path/old-manifest.yaml
  kubectl get secret,pvc --namespace "$NAMESPACE"
  kubectl get secret pgadmin-env --namespace "$NAMESPACE" -o name
  kubectl get pvc --namespace "$NAMESPACE" -o wide
  ```

  Protect the files containing Helm values; old values may contain credentials.
- Confirm the old appstore primary Secret contains the required keys and that
  the old `APPSTORE_SECRET_KEY` is the signing key currently used by the
  application. Do not replace it with a newly generated value. Confirm that
  `pgadmin-env` contains the existing pgAdmin password if pgAdmin is enabled.
- Merge the old standalone appstore configuration under the umbrella's
  `appstore:` key. Do not rely on `--reuse-values` when changing from a
  standalone chart to `helx-chart`; the value hierarchy changes and the old
  root-level values will not automatically become appstore subchart values.
- Preserve the old PostgreSQL and user-storage settings. If the release uses
  existing PVCs, do not allow the new values to create replacement claims with
  different names. Back up the PostgreSQL volume and appstore data before the
  upgrade.
- If the umbrella chart is deploying other services, review their values and
  dependencies separately. Disable unrelated dependencies only when that is
  correct for the target environment; do not use an LDAP-only example as a
  complete appstore production values file.
- Build or otherwise obtain the exact chart dependencies required by the current
  chart using the repository's registry credentials. The current appstore chart
  depends on `helx-common` and PostgreSQL, and the umbrella chart consumes the
  published appstore dependency.

### Upgrade procedure

1. Create a protected merged values file. For the normal automatic path, leave
   `appstore.secret.existingSecret` empty, leave
   `appstore.secret.externalSecret.enabled` false, and leave
   `appstore.secret.migration.enabled` true. Set the existing PVC names and
   preserve the old database configuration.
2. Build dependencies with the repository's normal credentials:

   ```sh
   helm dependency build deploy/helm/helx-chart
   ```

3. Render the chart to inspect names, PVC claims, and Deployment environment
   sources. A client-side render is useful for structure but cannot validate
   migrated Secret contents. For a cluster-aware validation, use a server-side
   dry run against the target cluster:

   ```sh
   helm upgrade "$RELEASE" deploy/helm/helx-chart \
     --namespace "$NAMESPACE" \
     --values /secure/path/appstore-migration-values.yaml \
     --dry-run=server --debug
   ```

   Confirm that the Deployment consumes the managed Secret target, the
   PostgreSQL settings point at the existing database, and the generated
   `pgadmin-env` Secret retains its existing data. Do not treat a client-side
   `helm template` or Argo CD client-side render as proof that lookup-based
   migration succeeded.
4. Run the live upgrade with the same release name. Include the complete
   production values and the merged migration values; do not use `--install`:

   ```sh
   helm upgrade "$RELEASE" deploy/helm/helx-chart \
     --namespace "$NAMESPACE" \
     --values /secure/path/production-values.yaml \
     --values /secure/path/appstore-migration-values.yaml \
     --wait --timeout 15m
   ```

   If the old deployment is being upgraded with the standalone appstore chart
   rather than the umbrella chart, use the corresponding current appstore chart
   path and keep the same release name and namespace.
5. If the migration fails required-key validation, do not delete the old Secret.
   Correct the source Secret or add only the missing key to
   `appstore.secret.values`, then rerun the upgrade. Existing persisted values
   take precedence over the fallback values.

### Verification after the upgrade

Before declaring the migration complete, verify the release, pods, Secrets, and
PVCs without printing Secret data:

```sh
helm status "$RELEASE" --namespace "$NAMESPACE"
kubectl get deployment,pods,pvc --namespace "$NAMESPACE"
kubectl get secret pgadmin-env --namespace "$NAMESPACE" -o name
kubectl get secret "<appstore-fullname>-secrets" --namespace "$NAMESPACE" -o name
kubectl get pvc "<postgresql-pvc-name>" --namespace "$NAMESPACE" \
  -o jsonpath='{.metadata.uid}{"\n"}'
```

Also verify that:

- the appstore pod becomes Ready and connects to the existing PostgreSQL
  database or SQLite claim;
- the managed appstore Secret contains the required current keys, including
  `SECRET_KEY` and `PG_DB_PASSWORD` when applicable, without exposing their
  values;
- the target Secret has the migration annotation
  `appstore.helxplatform.io/migrated-from` pointing to the old appstore Secret
  name on the first chart-managed migration;
- `pgadmin-env` still exists and its existing password remains valid;
- the PostgreSQL PVC UID and any SQLite/user-storage PVC names are unchanged;
- any enabled auxiliary appstore services listed above still have an explicit,
  reviewed Secret ownership plan.

### After a successful migration

After the new appstore pod and data access have been validated:

- Set `appstore.secret.migration.enabled: false` on a subsequent upgrade if no
  further legacy fallback or retention rendering is needed. Keep the migrated
  target Secret as the canonical Secret. The first migration leaves the old
  primary Secret retained with `helm.sh/resource-policy: keep`; retain it and a
  database backup until the application's normal recovery/retention period has
  passed.
- Keep `appstore.secret.values` stable. It is not a credential-rotation
  mechanism, and values for keys already persisted in the Secret are ignored.
- Keep `pgadmin-env` in place while pgAdmin is enabled. Its existing data is
  preserved on later upgrades by the same lookup-based helper.
- Do not delete or recreate the database PVC, SQLite PVC, user-storage PVC, or
  other application data claims as part of routine chart upgrades.

If the deployment is managed by Argo CD, perform the first handoff with a
cluster-aware Helm upgrade or pre-populate a caller-managed/ExternalSecret target
with the complete current key set. Argo CD's normal client-side Helm rendering
cannot read the old Secret through `lookup`; without one of those precautions,
it can render fallback/random values instead of the live migrated values.

## HeLx LDAP

This procedure is for an existing HeLx LDAP deployment that:

- was installed from an older version of the `helx-ldap` chart rather than as a
  dependency of `deploy/helm/helx-chart`;
- was deployed into the same Kubernetes namespace that will host the updated
  deployment; and
- is being upgraded using the **same Helm release name**.

The old deployment may have been installed with a standalone chart. Helm can
upgrade that release using the umbrella chart, provided the release name is
unchanged and unrelated umbrella-chart dependencies are disabled or configured
for the target environment.

This migration concerns the HeLx LDAP service only. `ldap-sync` is a separate
service and is not migrated by this procedure; do not confuse its deployment,
configuration, or data with the HeLx LDAP StatefulSet and PVC.

### Required conditions

The following are necessary for the automatic migration path:

1. **The existing deployment must be a Helm release.** The migration hooks run
   during `helm upgrade`; they intentionally fail during a fresh install.
2. **The namespace and Helm release name must remain the same.** Do not install
   the new umbrella chart under a second release name while the old release is
   still managing the HeLx LDAP StatefulSet. If the release name must change,
   use a separately planned ownership handoff instead of this runbook.
3. **The HeLx LDAP data PVC must be identified and `Bound`.** The migration
   reuses the PVC and its backing volume; it does not copy data to a new PVC.
4. **The adopted deployment must run as one replica.** The new chart requires
   `openldap.replicaCount: 1` when `openldap.persistence.existingClaim` is set.
   This procedure does not merge data from multiple StatefulSet replicas.
5. **The old credentials must be available.** The canonical Secret must contain
   `LDAP_ADMIN_PASSWORD` and `LDAP_CONFIG_ADMIN_PASSWORD`, whether it is already
   named `openldap-credentials` or must be copied from a differently named
   legacy Secret.
6. **The deployer must have permission to run the migration hook.** The hook
   needs namespace-scoped access to inspect PVCs and pods, and to scale and
   delete the selected old StatefulSet controller.

### Recommended preparation

Perform these steps before the upgrade:

- Schedule a maintenance window. The old HeLx LDAP pod is stopped before the
  new StatefulSet starts, so a brief service interruption is expected.
- Back up the HeLx LDAP volume or create a verified storage snapshot. The hook
  preserves the PVC but does not create a backup or copy its contents.
- Record the live object names, UIDs, and release metadata. The default names
  are usually:
  - StatefulSet: `openldap`
  - PVC: `data-openldap-0`
  - credentials Secret: `openldap-credentials`
- Inspect the old release values and manifest, keeping the output in a secure
  location because values may contain credentials:

  ```sh
  helm get values "$RELEASE" --namespace "$NAMESPACE" --all
  helm get manifest "$RELEASE" --namespace "$NAMESPACE"
  kubectl get statefulset,pvc,secret --namespace "$NAMESPACE"
  ```

- Compare the old configuration with the new chart values. Preserve any
  intentional settings for the naming context, administrator DN, anonymous
  access, resource limits, security context, and storage class. In particular,
  review `openldap.global.ldapDomain`, `configuration.baseDN`,
  `configuration.adminDN`, `openldap.env`, and
  `configuration.anonymousAccess`.
- Prefer setting `openldap.migration.legacyStatefulSet` explicitly when moving
  from an older standalone chart. Automatic discovery expects the current
  OpenLDAP labels and the same Helm release label; an explicit name avoids
  ambiguity when the old chart used different labels.
- Record the PVC UID before the upgrade:

  ```sh
  kubectl get pvc "$LEGACY_PVC" --namespace "$NAMESPACE" \
    -o jsonpath='{.metadata.uid}{"\n"}'
  ```

### Migration values

Start with
`deploy/helm/helx-chart/examples/ldap-migration-values.yaml`, but replace all
example names and merge the settings into the production values used for the
upgrade. That example disables unrelated umbrella dependencies for a HeLx
LDAP-only deployment; do not replace required production configuration with it
without reviewing the result.

At minimum, configure the following values:

```yaml
helx-ldap:
  enabled: true
  openldap:
    migration:
      enabled: true
      legacyPvc: "data-openldap-0"
      # Recommended for an old standalone release.
      legacyStatefulSet: "openldap"
    persistence:
      # Must remain set after the migration.
      existingClaim: "data-openldap-0"
  secret:
    # The canonical Secret consumed by the upstream OpenLDAP dependency.
    existingSecret: openldap-credentials
```

`legacyPvc` and `persistence.existingClaim` must be exactly the same live PVC
name. Replace `data-openldap-0` when the old StatefulSet or volume template used
a different name.

#### Credentials Secret cases

If the old Secret is already `openldap-credentials` and is caller-managed, leave
Secret migration disabled:

```yaml
helx-ldap:
  secret:
    existingSecret: openldap-credentials
    migration:
      enabled: false
```

If the old Secret has a different name, enable the one-time copy into the
canonical target:

```yaml
helx-ldap:
  secret:
    existingSecret: openldap-credentials
    migration:
      enabled: true
      legacySecret: "old-helx-ldap-credentials"
```

The Secret migration runs as a live Helm pre-upgrade hook, validates the two
required credential keys, copies the data without deleting the old Secret, and
leaves `openldap-credentials` caller-managed for future upgrades. It cannot be
used with `secret.externalSecret.enabled: true` during the same migration.

The normal supported path assumes the existing canonical Secret is
caller-managed. If the old chart created a Helm-managed credentials Secret,
verify its ownership before upgrading; do not assume that setting
`secret.existingSecret` alone will preserve a resource that the old release
manifest owned and the new chart no longer renders. Establish a deliberate
caller-managed or external-secret strategy first, without committing plaintext
credentials to the repository.

### Upgrade procedure

1. Set the shell variables to the actual release, namespace, and live PVC:

   ```sh
   export RELEASE="helx-ldap"
   export NAMESPACE="your-namespace"
   export LEGACY_PVC="data-openldap-0"
   export LEGACY_STATEFULSET="openldap"
   export LEGACY_SECRET="openldap-credentials"
   ```

2. Confirm the old HeLx LDAP StatefulSet, PVC, and credentials Secret. Verify
   that the PVC is `Bound` and that the selected StatefulSet is the one using
   that PVC:

   ```sh
   kubectl get statefulset "$LEGACY_STATEFULSET" \
     --namespace "$NAMESPACE" -o yaml
   kubectl get pvc "$LEGACY_PVC" \
     --namespace "$NAMESPACE" -o wide
   kubectl get secret "$LEGACY_SECRET" \
     --namespace "$NAMESPACE" -o name
   ```

3. Build the chart dependencies using the repository's normal registry
   credentials:

   ```sh
   helm dependency build deploy/helm/helx-chart
   ```

4. Render the upgrade values and inspect the HeLx LDAP resources. Because
   Secret migration uses `lookup`, disable that flag for a client-side render,
   or use a server-side dry run against the target cluster:

   ```sh
   helm template "$RELEASE" deploy/helm/helx-chart \
     --namespace "$NAMESPACE" \
     --is-upgrade \
     --values deploy/helm/helx-chart/examples/ldap-migration-values.yaml \
     --set helx-ldap.secret.migration.enabled=false
   ```

   Confirm that the rendered HeLx LDAP StatefulSet contains a direct
   `persistentVolumeClaim.claimName` for the adopted PVC and does not contain
   `volumeClaimTemplates`. Confirm that the pre-upgrade migration Job and its
   namespace-scoped RBAC are rendered. Review the rendered `ldap-sync` resources
   separately; they are not part of this data migration.

5. Run the live upgrade with the same release name. Use the complete production
   values plus the migration settings; do not blindly use `--reuse-values` when
   moving from a standalone chart because the value hierarchy may differ:

   ```sh
   helm upgrade "$RELEASE" deploy/helm/helx-chart \
     --namespace "$NAMESPACE" \
     --values path/to/production-values.yaml \
     --values path/to/merged-helx-ldap-migration-values.yaml \
     --wait \
     --timeout 15m
   ```

   The pre-upgrade hook checks the PVC, verifies the selected StatefulSet's PVC
   mapping, scales the old StatefulSet to zero, waits for its pods to terminate,
   and deletes only the old StatefulSet controller with orphan propagation.
   Helm then creates the new StatefulSet using the existing PVC. The PVC and
   backing volume are neither deleted nor copied.

6. If the Secret has a different legacy name, run this as a live upgrade rather
   than relying on `helm template` or Argo CD's client-side rendering. The
   Secret hook uses the Kubernetes API to read the legacy Secret.

### Verification after the upgrade

Verify all of the following before declaring the migration complete:

```sh
helm status "$RELEASE" --namespace "$NAMESPACE"
kubectl get statefulset,pods,pvc --namespace "$NAMESPACE"
kubectl get pvc "$LEGACY_PVC" --namespace "$NAMESPACE" \
  -o jsonpath='{.metadata.uid}{"\n"}'
kubectl get statefulset openldap --namespace "$NAMESPACE" \
  -o jsonpath='{.spec.template.spec.volumes[?(@.name=="data")].persistentVolumeClaim.claimName}{"\n"}'
kubectl get jobs --namespace "$NAMESPACE" \
  -l app.kubernetes.io/component=configuration
```

The PVC UID must match the value recorded before the upgrade, and the new
StatefulSet must report the adopted PVC as its direct `claimName`. Confirm that
its pod becomes Ready, the HeLx LDAP configuration Job succeeds, and clients can
connect through the stable `openldap` Service. If Secret migration was enabled,
verify the canonical Secret exists and contains both required keys without
printing the values.

### After a successful migration

On the next upgrade:

- Set `helx-ldap.openldap.migration.enabled: false`.
- Set `helx-ldap.secret.migration.enabled: false`.
- Keep `helx-ldap.openldap.persistence.existingClaim` set permanently.
- Retain the old Secret and any old backup until the new deployment has been
  validated and the normal retention policy permits cleanup.
- Do not scale a second HeLx LDAP StatefulSet against the adopted `ReadWriteOnce`
  PVC.

The migration hook is intentionally opt-in and destructive to the old
StatefulSet controller. If a later part of the upgrade fails, Helm cannot restore
the old controller automatically, and `--atomic` cannot undo the controller handoff.
The PVC remains available for another recovery or upgrade attempt, but restoring
service may require deploying the previous chart/controller against that PVC.

For the chart-specific defaults and migration values, see
[`services/helx-ldap/README.md`](services/helx-ldap/README.md) and
[`deploy/helm/helx-chart/examples/ldap-migration-values.yaml`](deploy/helm/helx-chart/examples/ldap-migration-values.yaml).
