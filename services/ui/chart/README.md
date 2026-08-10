# ui

A Helm chart for Kubernetes

![Version: 1.5.0](https://img.shields.io/badge/Version-1.5.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 6.3.0](https://img.shields.io/badge/AppVersion-6.3.0-informational?style=flat-square)

## About HELX-UI

HeLx UI provides a configurable user interface for the [HeLx](https://helxplatform.github.io/) platform.
The UI supports access to a concept-based search tool, and scalebale configurable computing environments.
The helm chart in this repo has the configurations necessary for the deployment to work with other components of the HeLx platform.
Configurations support the ui implementation at [HeLx-UI Codebase](https://github.com/helxplatform/helx-ui).

## CI/CD

When the main branch of this chart is updated, using Github Actions we send the updated version to helm-charts repo to be indexed and packaged automatically.

Additionally there is a workflow that allows bumping the chart version, if this is all that is needed to the cooresponding version of the appstore repository.

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| affinity | object | `{}` |  |
| autoscaling.enabled | bool | `false` |  |
| autoscaling.maxReplicas | int | `100` |  |
| autoscaling.minReplicas | int | `1` |  |
| autoscaling.targetCPUUtilizationPercentage | int | `80` |  |
| config.analytics.enabled | bool | `false` |  |
| config.analytics.platform | string | `"google"` |  |
| config.analytics.token | string | `""` |  |
| config.appstore_asset_base_url | string | `"https:\\/\\/raw.githubusercontent.com\\/helxplatform\\/appstore"` |  |
| config.appstore_asset_branch | string | `"master"` |  |
| config.brand_description | object | `{"html":""}` | Multiline value (4 space indent) with html code describing the deployment, will be displayed on the Workspaces login page |
| config.brand_name | string | `""` |  |
| config.default_space | string | `"search"` | Define landing page when the deployment is loaded. Default is support. Acceptable values: "workspaces", "search", "support" |
| config.hidden_result_tabs | string | `""` |  |
| config.login_title | string | `""` | Heading on the Workspaces Login screen. If not set, this will be "<config.meta.title> Workspaces" |
| config.meta.description | string | `"HeLx UI"` | Page description with a link preview. |
| config.meta.title | string | `"HeLx UI"` | Browser tab title and title on "Workspaces" login page |
| config.search.enabled | string | `"true"` | If search page should show up. This is configured to work with DUG |
| config.search.tour_enabled | string | `"false"` | - If guided tour for search should show up |
| config.search.url | string | `"https:\\/\\/helx.renci.org"` |  |
| config.support | object | `{"faqs_url":"","help_portal_url":"","howto_video_url":"","intro_video_url":"","user_guide_url":""}` | Support page sections to display. If a link is provided, the corresponding section will be displayed |
| config.support.faqs_url | string | `""` | Link for a page with FAQs. |
| config.support.help_portal_url | string | `""` | Link to portal for submitting tickets/requesting features/reporting bugs |
| config.support.howto_video_url | string | `""` | Link to a video on how to use the deployment |
| config.support.intro_video_url | string | `""` | Link to an introduction video for the deployment. |
| config.support.user_guide_url | string | `""` | Link to a page with user instructions on how to use the deployment |
| config.tranql_url | string | `"https:\\/\\/helx.renci.org\\/tranql\\/"` |  |
| config.workspaces.enabled | string | `"true"` | Allow Workspaces. |
| fullnameOverride | string | `""` |  |
| image.pullPolicy | string | `"IfNotPresent"` |  |
| image.repository | string | `"helxplatform/helx-ui"` |  |
| image.tag | string | `""` | Overrides the image tag whose default is the appVersion supplied in umbrella chart. |
| imagePullSecrets | list | `[]` |  |
| ingress.annotations | object | `{}` |  |
| ingress.className | string | `""` |  |
| ingress.enabled | bool | `false` |  |
| ingress.hosts[0].host | string | `"chart-example.local"` |  |
| ingress.hosts[0].paths[0].path | string | `"/"` |  |
| ingress.hosts[0].paths[0].pathType | string | `"ImplementationSpecific"` |  |
| ingress.tls | list | `[]` |  |
| nameOverride | string | `""` |  |
| nodeSelector | object | `{}` |  |
| podAnnotations | object | `{}` |  |
| podSecurityContext | object | `{}` |  |
| replicaCount | int | `1` |  |
| resources | object | `{}` |  |
| securityContext | object | `{}` |  |
| service.port | int | `80` |  |
| service.type | string | `"ClusterIP"` |  |
| serviceAccount.annotations | object | `{}` | Annotations to add to the service account |
| serviceAccount.create | bool | `true` | Specifies whether a service account should be created |
| serviceAccount.name | string | `""` | The name of the service account to use. If not set and create is true, a name is generated using the fullname template |
| tolerations | list | `[]` |  |

----------------------------------------------
Autogenerated from chart metadata using [helm-docs v1.11.3](https://github.com/norwoodj/helm-docs/releases/v1.11.3)
