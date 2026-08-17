# helx-ldap Helm chart

This chart wraps the upstream `openldap-stack-ha` chart and adds the HeLx LDAP
configuration required by the `memberOf` overlay, anonymous-access ACLs, and the
`helxUser` schema used by the current user-management scripts. The schema includes
`runAsUser`, `runAsGroup`, `fsGroup`, `supplementalGroups`, and `userAlias`.

The OpenLDAP deployment is always included when this wrapper chart is enabled.
The HeLx-specific `cn=config` changes run as a Helm `post-install,post-upgrade`
Job after LDAP becomes ready. The Job is idempotent for a completed configuration,
discovers the MDB database DN instead of assuming `olcDatabase={2}mdb`, and
locates the generated `helxUser` schema DN dynamically.

By default, anonymous binding and the develop branch's anonymous-read ACL are
enabled. The ACL permits anonymous reads of user password hashes, so disable both
`configuration.anonymousAccess.enabled` and
`openldap.env.LDAP_ALLOW_ANON_BINDING` when that behavior is not required.

## Credentials

Create a Secret before installing with these keys:

- `LDAP_ADMIN_PASSWORD`
- `LDAP_CONFIG_ADMIN_PASSWORD`

The Secret name must match `openldap.global.existingSecret`, or
`configuration.existingSecret` if it is set.

## Dependency preparation

From the repository root:

```sh
helm dependency build services/helx-ldap/chart
```

Use `helm dependency update services/helx-ldap/chart` only when intentionally
changing the dependency versions; review the resulting `Chart.lock` before
committing it. The wrapper chart uses the upstream chart version `4.3.3`. The configuration Job
uses the same image as the OpenLDAP dependency by default; that image must contain
`/bin/sh`, `awk`, `sed`, `grep`, `ldapsearch`, and `ldapmodify`.

The current wrapper defaults also preserve the develop deployment's OpenLDAP
resources and `LDAP_ALLOW_ANON_BINDING=yes` setting. On OpenShift, use the
upstream value below so the SCC assigns the filesystem group, matching the
legacy generator's `openshift: true` behavior:

```yaml
openldap:
  podSecurityContext:
    enabled: false
```

`configuration.baseDN` and `configuration.adminDN` can override the values
derived from the OpenLDAP domain and admin user. Existing installations with
the former `kubernetesSC` schema must be migrated explicitly before enabling
this chart version because both schemas use the same OID.
