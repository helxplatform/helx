import logging
import os
import re
import sys

import appstore
# This is really not ideal but tycho imports are broken without path injection
sys.path.insert(0, os.path.dirname(appstore.__file__))

from appstore.tycho.context import ContextFactory
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Environment config
DAEMONSET_NAME = os.environ.get("PREPULLER_DAEMONSET_NAME", "app-image-prepuller")
DAEMONSET_NAMESPACE = os.environ.get("PREPULLER_NAMESPACE", "default")
APP_REGISTRY_REPO = os.environ["APP_REGISTRY_REPO"]
APP_REGISTRY_BRANCH = os.environ["APP_REGISTRY_BRANCH"]
APP_REGISTRY_BRAND = os.environ["APP_REGISTRY_BRAND"]


def fetch_image_list() -> list[dict]:
    """Return a list of images that should be pre-pulled on every node.

    Each entry is a dict with at minimum an `image` and `name` key, and optionally:
    - `run_as_user`: an integer UID if the image requires a specific user (e.g. 0 for root)
    """
    factory = ContextFactory()
    tycho_config_url = APP_REGISTRY_REPO + ("/" if not APP_REGISTRY_REPO.endswith("/") else "") + APP_REGISTRY_BRANCH
    tycho = factory.get(
        context_type="live",
        product=APP_REGISTRY_BRAND,
        tycho_config_url=tycho_config_url
    )
    image_list = []
    for app_id in tycho.apps:
        app_spec = tycho.get_definition(app_id)
        for service_id in app_spec["services"]:
            service_spec = app_spec["services"][service_id]
            image = service_spec["image"]
            image_list.append({
                "name": app_id if len(app_spec["services"]) == 1 else f"{app_id}_{service_id}",
                "image": image
            })
    return image_list


def build_init_containers(images: list[dict]) -> list[client.V1Container]:
    """Build a list of init container specs from the image list."""
    containers = []
    for entry in images:
        image = entry["image"]
        name = entry["name"]

        # Run all init containers as root to avoid "no users found" errors
        # from images that define non-standard users (e.g. pgadmin). This is
        # safe because the containers only execute "exit 0".
        security_context = client.V1SecurityContext(
            run_as_user=entry.get("run_as_user", 0),
        )

        containers.append(
            client.V1Container(
                name=name,
                image=image,
                image_pull_policy="IfNotPresent",
                command=["/bin/sh", "-c", "exit 0"],
                security_context=security_context,
            )
        )
    return containers


def patch_daemonset(
    apps_api: client.AppsV1Api,
    init_containers: list[client.V1Container],
) -> None:
    """Patch the prepuller DaemonSet so its init containers match the desired list."""
    patch = {
        "spec": {
            "template": {
                "spec": {
                    "initContainers": [
                        client.ApiClient().sanitize_for_serialization(c)
                        for c in init_containers
                    ]
                }
            }
        }
    }
    apps_api.patch_namespaced_daemon_set(
        name=DAEMONSET_NAME,
        namespace=DAEMONSET_NAMESPACE,
        body=patch,
    )
    logger.info(
        "Patched DaemonSet %s/%s with %d init container(s)",
        DAEMONSET_NAMESPACE,
        DAEMONSET_NAME,
        len(init_containers),
    )


def main() -> None:
    # Load in-cluster config when running inside a pod, otherwise fall back to
    # the local kubeconfig (for development).
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except config.ConfigException:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig")

    apps_api = client.AppsV1Api()

    images = fetch_image_list()
    if images is None:
        logger.error("Image list is empty -- nothing to pull")
        sys.exit(1)

    init_containers = build_init_containers(images)
    patch_daemonset(apps_api, init_containers)
    logger.info("Sync complete")


if __name__ == "__main__":
    main()
