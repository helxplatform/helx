# appstore

A Helm chart for Kubernetes

![Version: 6.0.0](https://img.shields.io/badge/Version-6.0.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 4.4.1](https://img.shields.io/badge/AppVersion-4.4.1-informational?style=flat-square)

## CI/CD

When the main branch of this chart is updated, using Github Actions we send the updated version to helm-charts repo to be indexed and packaged automatically.

Additionally there is a workflow that allows bumping the chart version, if this is all that is needed to the cooresponding version of the appstore repository.

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ACCOUNT_DEFAULT_HTTP_PROTOCOL | string | `"http"` | Choose http or https for the protocol that is used by external users to access the appstore web service. |
| SET_BUILD_ENV_FROM_FILE | bool | `false` | Set environment variables from a file. |
| affinity | object | `{}` |  |
| ambassador.flag | bool | `true` | register appstore with ambassador flag: <True or False> |
| apps.DATASOURCE_CONNECTION_URL | string | `""` |  |
| apps.DATASOURCE_PASSWORD | string | `""` |  |
| apps.DATASOURCE_USERNAME | string | `"ohdsi"` |  |
| apps.DICOMGH_GOOGLE_CLIENT_ID | string | `""` |  |
| apps.FLYWAY_DATASOURCE_CONNECTION_URL | string | `""` |  |
| apps.FLYWAY_DATASOURCE_PASSWORD | string | `""` |  |
| apps.FLYWAY_DATASOURCE_USERNAME | string | `"ohdsi"` |  |
| apps.HELX_DB_HOSTNAME | string | `""` | Specify the database hostname used for pgAdmin's clients to connect to. If specified this replaces 'mimic-postgresql' in the pgadmin4.db configuration file. |
| apps.PGADMIN_DISABLE_POSTFIX | string | `"true"` |  |
| apps.PGADMIN_EMAIL | string | `"user@domain.com"` | Specify email for pgAdmin user. |
| apps.PGADMIN_LISTEN_PORT | string | `"80"` |  |
| apps.WEBTOP_PGID | string | `"1000"` | PGID variable in webtop specifies the GID to switch the user to after initialization. |
| apps.WEBTOP_PUID | string | `"1000"` | PUID variable in webtop specifies the UID to switch the user to after initialization. |
| appstoreEntrypointArgs | string | `"make start"` | Allow for a custom entrypoint command via the values file. |
| atlas.enabled | bool | `true` | Disabling will turn off the creation of secrets/configmaps for Atlas |
| db | object | `{"name":"appstore","port":5432}` | appstore database settings |
| debug | string | `""` |  |
| django.ALLOW_DJANGO_LOGIN | string | `""` | show Django log in fields (true | false) |
| django.ALLOW_SAML_LOGIN | string | `""` | show SAML log in fields (true | false) |
| django.AUTO_WHITELIST_PATTERNS | list | `[]` | Note that these only run on a user's primary alias. If a user has primary@cs.unc.edu as their primary alias, and secondary@renci.org as a secondary alias, they will only be whitelisted automatically if cs.unc.edu emails are allowed. ex. Whitelist all RENCI emails - "^[A-Za-z0-9._%+-]+@renci\\.org$" ex. Whitelist all UNC emails - "^[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\\.)?unc\\.edu$" ex. Whitelist CS dept. (grad./prof.) UNC emails - "^[A-Za-z0-9._%+-]+@cs\\.unc\\.edu$" |
| django.DEV_PHASE | string | `"live"` | should be 'live' unless you are doing some kind of development |
| django.DOCKSTORE_APPS_BRANCH | string | `"v1.6.0"` | Specify the git branch to use for HeLx app specifications.  When declaring 'tycho.externalAppRegistryRepo' leave this as an empty string. |
| django.IMAGE_DOWNLOAD_URL | string | `""` | Specify URL to use for the "Image Download" link on the top part of website. |
| django.PRODUCT_LINKS | list | `[]` |  |
| django.SESSION_IDLE_TIMEOUT | string | `"2592000"` | idle timeout for user web session |
| djangoSettings | string | `"helx"` | set the theme for appstore (bdc, braini, restartr, scidas) |
| extraEnv | object | `{}` |  |
| fetcherImage.pullPolicy | string | `"IfNotPresent"` | pull policy |
| fetcherImage.repository | string | `"helxplatform/url-fetch"` | repository where image is located |
| fetcherImage.tag | string | `"latest"` |  |
| fullnameOverride | string | `""` |  |
| global.ambassador_id | string | `nil` | specify the id of the ambassador for Tycho-launched services. |
| global.ambassador_mapping_name | string | `"appstore-mapping"` | specify the mapping name for ambassador |
| global.ambassador_service_name | string | `"ambassador"` | specify the service name for ambassador |
| global.imageRegistry | string | `"containers.renci.org"` | container image registry to use for Bitnami images |
| global.security.allowInsecureImages | bool | `true` | load container images from non-Bitnami container registry servers |
| global.stdnfsPvc | string | `"stdnfs"` | the name of the PVC to use for user's files |
| graderApiUrl | string | `""` |  |
| gunicorn.workers | int | `5` | Set the number of gunicorn workers.  (2*CPU)+1 is recommended. |
| image.pullPolicy | string | `"IfNotPresent"` | pull policy |
| image.repository | string | `"containers.renci.org/helxplatform/appstore"` | repository where image is located |
| image.tag | string | `nil` | Overrides the image tag whose default is the chart appVersion. Set to "" before release! |
| imagePostgresql.pullPolicy | string | `"IfNotPresent"` | pull policy |
| imagePostgresql.repository | string | `"containers.renci.org/bitnami/postgresql"` | repository where postgresql image is located |
| imagePostgresql.tag | string | `"17.6.0-debian-12-r0"` | Image tag for postgresql, coordinate this with postgresql dependency. |
| imagePullSecrets | list | `[]` | credentials for a private repo |
| imagej.enabled | bool | `true` | Disabling will turn off the creation of secrets/configmaps for ImageJ |
| irods.enabled | bool | `false` | enable branded iRODS support; provide its environment variables through the selected appstore Secret. |
| irodsUnbranded.IROD_USER_VALUES | object | `{}` |  |
| irodsUnbranded.enabled | bool | `false` |  |
| ldap.enabled | bool | `false` |  |
| ldap.groupDN | string | `"cn=users,ou=groups,dc=example,dc=org"` |  |
| ldap.searchBase | string | `"ou=users,dc=example,dc=org"` |  |
| ldap.uri | string | `"ldap://openldap"` |  |
| logLevel | string | `"WARNING"` | Set the log level for the application.  (DEBUG INFO WARNING ERROR CRITICAL) |
| logsStorageAppstore | object | `{"claimName":null,"createPVC":false,"existingClaim":false,"storageClass":null,"storageSize":"2Gi"}` | Settings for django logs persistence. |
| logsStorageAppstore.claimName | string | `nil` | Specify the claim name if it pre-exists or it defaults to appstore-logs-pvc. |
| logsStorageAppstore.existingClaim | bool | `false` | Set to true if a claim has been created outside of the appstore chart. |
| nameOverride | string | `""` |  |
| networkPolicyLabels.role | string | `"appstore"` |  |
| nodeSelector | object | `{}` |  |
| octave.enabled | bool | `true` | Disabling will turn off the creation of secrets/configmaps for Octave |
| pgadmin.enabled | bool | `true` | Disabling will turn off the creation of secrets/configmaps for PgAdmin |
| podAnnotations | object | `{}` |  |
| podSecurityContext | object | `{}` |  |
| postgresql | object | `{"audit":{"logConnections":true,"logHostname":true},"enabled":true,"global":{"postgresql":{"auth":{"database":"appstore-oauth","password":"renciAdmin","postgresPassword":"adminPass","username":"renci"}}},"networkPolicyEnabled":true,"persistence":{"existingClaim":"appstore-postgresql-pvc","storageClass":null},"primary":{"labels":{"np-label":"appstore-db"},"podLabels":{"np-label":"appstore-db"}},"volumePermissions":{"enabled":true}}` | postgresql settings |
| postgresql.audit | object | `{"logConnections":true,"logHostname":true}` | postgresql logs |
| postgresql.global.postgresql | object | `{"auth":{"database":"appstore-oauth","password":"renciAdmin","postgresPassword":"adminPass","username":"renci"}}` | postgresql credentials |
| postgresql.networkPolicyEnabled | bool | `true` | enable/disable postgresql network policy, allows traffic to and from appstore pod only. |
| postgresql.persistence | object | `{"existingClaim":"appstore-postgresql-pvc","storageClass":null}` | postgresql persistence storage |
| postgresql.primary | object | `{"labels":{"np-label":"appstore-db"},"podLabels":{"np-label":"appstore-db"}}` | postgresql labels |
| replicaCount | int | `1` |  |
| resources.limits.cpu | string | `"500m"` |  |
| resources.limits.memory | string | `"1024Mi"` |  |
| resources.requests.cpu | string | `"200m"` |  |
| resources.requests.memory | string | `"300Mi"` |  |
| saml.ASSERTION_URL | string | `""` |  |
| saml.AUTHORITY_URL | string | `""` |  |
| saml.ENTITY_ID | string | `""` |  |
| saml.IDP_ENTITY_ID | string | `""` | IdP entity ID to select from the metadata source (required when the source is a federation aggregate, e.g. "https://sso.unc.edu/idp") |
| saml.PROVIDER_NAME | string | `"Single Sign-On"` | human-readable name for the SAML provider, shown on the login page |
| saml.PROVIDER_SLUG | string | `"saml"` | URL slug under /accounts/saml/<slug>/ for the SAML provider (e.g. "unc") |
| saml.cache.APPSTORE_DIRECTORY | string | `"/saml"` |  |
| saml.cache.APPSTORE_FILE | string | `"saml_metadata.xml"` |  |
| saml.cache.FETCH_FILE | string | `"/data/saml_metadata.xml"` |  |
| saml.cache.FETCH_INTERVAL | string | `"60000"` |  |
| saml.cache.claimName | string | `"saml-cache"` |  |
| saml.cache.enabled | bool | `false` |  |
| saml.cache.storageClass | string | `""` |  |
| saml.cache.storageSize | string | `"20M"` |  |
| secret.existingSecret | string | `""` | Name of a Secret containing the appstore environment variables. When set, the chart does not create or manage a Secret. For an existing legacy release, leave this empty to let the chart migrate the old primary Secret automatically. |
| secret.externalSecret | object | `{"enabled":false,"refreshInterval":"1h","remoteRef":"","secretStoreRef":{"kind":"SecretStore","name":"vault"},"targetName":""}` | Configure an ExternalSecret to populate the appstore Secret. This is mutually exclusive with secret.existingSecret. The external backend must be populated separately when migrating an existing release. |
| secret.externalSecret.targetName | string | `""` | Optional ESO target Secret name. Defaults to <fullname>-secrets. |
| secret.migration.enabled | bool | `true` | Enable automatic migration from the legacy appstore Secret. |
| secret.values | object | `{}` | Key/value pairs used to create the appstore Secret when neither secret.existingSecret nor secret.externalSecret.enabled is set.  Keys are exposed unchanged as appstore container environment variables. Use these same names in this map, in the Secret named by existingSecret, or in the Secret returned by External Secrets.  During an upgrade from the legacy chart, existing Secret data takes priority over this map. The map only supplies missing keys; it does not rotate stored passwords or signing keys automatically. Values for keys already present in the persisted Secret are ignored; rotate those credentials in the canonical Secret instead.  Values are strings because Kubernetes Secret values are exposed as environment variables. Optional keys should be omitted unless the corresponding feature is enabled. |
| security.appEgressAllowedPods | list | `[]` |  |
| security.dnsPodSelector | object | `{}` |  |
| security.isolatedApps | bool | `true` |  |
| service.name | string | `"http"` |  |
| service.port | int | `80` |  |
| service.type | string | `"ClusterIP"` |  |
| serviceAccount.create | bool | `true` | specifies whether a service account should be created |
| serviceAccount.name | string | `nil` | The name of the service account to use. If not set and create is true, a name is generated using the fullname template |
| sqliteStorage | object | `{"claimName":null,"storageClass":null}` | Settings for django sqlite3 db file persistence, if postgresql is not enabled (postgresql.enabled: false). |
| sqliteStorage.claimName | string | `nil` | If a claim name is not specified, it defaults to appstore-oauth-pvc. |
| tolerations | list | `[]` |  |
| tycho.GPUResourceName | string | `"nvidia.com/gpu"` | The GPU resource name that a container can utilize.  Typically this is "nvidia.com/gpu", but other types exist, such as "nvidia.com/mig-1g.5gb" and other manufacturers have their own types. |
| tycho.appRoutingMode | string | `"proxy"` | How Tycho-launched apps are routed. "proxy" (default on this branch): ClusterIP + /private prefix, backend resolved by an external reverse proxy (resty) via appstore's /api/v1/private-route/ resolver — the de-Ambassador design. "ambassador" (legacy): emit the Ambassador Mapping annotation when Ambassador is present. "none": no routing wiring. |
| tycho.createHomeDirs | bool | `true` | Create Home and shared directories for users. |
| tycho.enableInitContainer | bool | `true` | Start the init container to take care of any needed tasks before the main container is started.  This can be to create certain directories or set file permissions. |
| tycho.enableTrashCli | bool | `false` | Enable trash-cli functionality in tycho-launched apps |
| tycho.externalAppRegistryAppSpecsDir | string | `"app-specs"` |  |
| tycho.externalAppRegistryBranch | string | `nil` | The branch that is appended to externalAppRegistryRepo when the external app registry is enabled. The full URL, using the repository below, would be 'https://github.com/helxplatform/helx-apps/raw/master/app-registry.yaml'. The default value is the AppVersion of this chart prefixed with a 'v' (ex. v2.0.0). |
| tycho.externalAppRegistryEnabled | bool | `false` | Enable/disable the external app registry file for Tycho. |
| tycho.externalAppRegistryRepo | string | `"https://github.com/helxplatform/helx-apps/raw"` | Can be set to a git repo URL for fetching the app registry file or defaults file.  Something in the form of 'https://github.com/helxplatform/helx-apps/raw'. |
| tycho.fsGroup | int | `0` | Application processes launched will also be part of this supplimentary group. |
| tycho.init | object | `{"resources":{"cpus":"250m","memory":"250Mi"}}` | Resource for Tycho init container. Defaults cpus|250m memory|250Mi |
| tycho.initImageRepository | string | `"busybox"` | The image repository to use for HeLx app init containers. |
| tycho.initImageTag | string | `"latest"` | The image tag to use for HeLx app init containers. |
| tycho.initRunAsGroup | int | `0` | Init processes will have this group permissions. |
| tycho.initRunAsNobodyGroup | int | `524288` | "Userless" init processes will have these group permissions. |
| tycho.initRunAsNobodyUser | int | `524288` | "Userless" init processes will run as this user. |
| tycho.initRunAsUser | int | `0` | Init processes will run as this user. |
| tycho.parent_dir | string | `"/home"` | directory that will be used to mount user's home directories in |
| tycho.runAsGroup | int | `0` | Application processes launched will have this group permissions. |
| tycho.runAsUser | int | `0` | Application processes launched will run as this user. |
| tycho.shared_dir | string | `"shared"` | name of directory to use for shared data |
| tycho.subpath_dir | string | `nil` | Name of directory to use for a user's home directory.  If null then the user's username will be used. |
| updateStrategy.type | string | `"Recreate"` | 'RollingUpdate' or 'Recreate'. Must use Recreate if mounting PVCs due to multi-attach errors. |
| useSparkServiceAccount | bool | `false` | Set to true, when using blackbalsam. |
| userStorage.createPVC | bool | `true` | Create a PVC for user's files.  If false then the PVC needs to be created outside of the appstore chart. |
| userStorage.nfs.createPV | bool | `false` |  |
| userStorage.nfs.path | string | `nil` |  |
| userStorage.nfs.server | string | `nil` |  |
| userStorage.retain | bool | `true` |  |
| userStorage.storageClass | string | `nil` |  |
| userStorage.storageSize | string | `"10Gi"` |  |
| webtop.enabled | bool | `true` | Disabling will turn off the creation of secrets/configmaps for Webtop |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.14.2](https://github.com/norwoodj/helm-docs/releases/v1.14.2)

