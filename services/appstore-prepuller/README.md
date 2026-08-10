# appstore-prepuller

Automatically pre-pulls container images on every node in a Kubernetes cluster so that first launches from the [HeLx Appstore](https://github.com/helxplatform/appstore) are fast.

## Overview

When a user launches an application for the first time on a node, the container runtime must pull the image before the pod can start. For large images this can add minutes of wait time. **appstore-prepuller** eliminates that delay by proactively pulling every registered application image onto every node in the cluster.

### Architecture

The system has two components:

| Component | Kubernetes Resource | Purpose |
|---|---|---|
| **Controller** | CronJob (every 5 min) | Fetches the current image list from the app registry and patches the DaemonSet |
| **Prepuller** | DaemonSet | Runs on every eligible node; its init containers pull the images |

```
 App Registry (Tycho API)
         |
         v
  +--------------+         patch initContainers         +------------------+
  |  Controller  | -------------------------------------> |    DaemonSet     |
  |  (CronJob)   |                                       | (all nodes)      |
  +--------------+                                       +------------------+
                                                          | init: pull img1 |
                                                          | init: pull img2 |
                                                          | ...             |
                                                          | main: pause     |
                                                          +------------------+
```

## Prerequisites

- Kubernetes 1.19+
- Helm 3
- Access to the HeLx app registry

## Installation

```bash
helm install appstore-prepuller ./chart \
  --namespace <namespace> \
  --set appRegistry.repo=<registry-url> \
  --set appRegistry.branch=<branch> \
  --set appRegistry.brand=<brand>
```

### Helm Values

| Parameter | Description | Default |
|---|---|---|
| `appRegistry.repo` | URL of the app registry | `""` (required) |
| `appRegistry.branch` | Git branch for the registry | `""` (required) |
| `appRegistry.brand` | Brand identifier | `""` (required) |
| `controller.image.repository` | Controller image | `containers.renci.org/helxplatform/appstore-prepuller` |
| `controller.image.tag` | Controller image tag | `latest` |
| `controller.schedule` | CronJob schedule | `*/5 * * * *` |
| `controller.resources` | Controller resource requests/limits | 50m-200m CPU, 64Mi-128Mi mem |
| `daemonset.nodeSelector` | Node selector for prepuller pods | `kubernetes.azure.com/mode: user` |
| `daemonset.tolerations` | Tolerations for prepuller pods | Tolerate all |
| `daemonset.pauseImage` | Pause image for the main container | `registry.k8s.io/pause:3.9` |
| `daemonset.resources` | DaemonSet resource requests/limits | 10m-50m CPU, 10Mi-20Mi mem |

## Development

### Building the Docker image

```bash
cd controller
docker build -t appstore-prepuller .
```

### Running locally

The controller can run outside the cluster using your local kubeconfig. Set the required environment variables first:

```bash
export APP_REGISTRY_REPO=<registry-url>
export APP_REGISTRY_BRANCH=<branch>
export APP_REGISTRY_BRAND=<brand>
export PREPULLER_NAMESPACE=<namespace>
export PREPULLER_DAEMONSET_NAME=app-image-prepuller

pip install -r controller/requirements.txt
python controller/prepuller.py
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `APP_REGISTRY_REPO` | App registry URL | (required) |
| `APP_REGISTRY_BRANCH` | App registry branch | (required) |
| `APP_REGISTRY_BRAND` | App registry brand | (required) |
| `PREPULLER_DAEMONSET_NAME` | Name of the DaemonSet to patch | `app-image-prepuller` |
| `PREPULLER_NAMESPACE` | Namespace of the DaemonSet | `default` |

## Project Structure

```
.
├── chart/                    # Helm chart
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
│       ├── _helpers.tpl      # Template helpers
│       ├── cronjob.yaml      # Controller CronJob
│       ├── daemonset.yaml    # Image prepuller DaemonSet
│       ├── rbac.yaml         # Role and RoleBinding
│       └── serviceaccount.yaml
└── controller/
    ├── Dockerfile
    ├── requirements.txt
    └── prepuller.py          # Controller logic
```

## License

[MIT](LICENSE)
