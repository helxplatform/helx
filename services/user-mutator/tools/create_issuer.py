#!/usr/bin/env python

import argparse
import yaml
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import os

def create_cluster_issuer_yaml():
    cluster_issuer = {
        "apiVersion": "cert-manager.io/v1",
        "kind": "ClusterIssuer",
        "metadata": {"name": "selfsigned"},
        "spec": {"selfSigned": {}}
    }
    return yaml.dump(cluster_issuer)

def check_cluster_issuer_exists(api_instance, name):
    try:
        cluster_issuers = api_instance.list_cluster_custom_object(
            group="cert-manager.io",
            version="v1",
            plural="clusterissuers"
        )
        for issuer in cluster_issuers.get('items', []):
            if issuer['metadata']['name'] == name:
                return True
        return False
    except ApiException as e:
        print(f"Error checking for existing ClusterIssuer: {e}")
        return False

def apply_yaml(yaml_content):
    config.load_kube_config()
    api_instance = client.CustomObjectsApi()

    if check_cluster_issuer_exists(api_instance, "selfsigned"):
        print("ClusterIssuer 'selfsigned' already exists in the cluster.")
        return

    try:
        api_response = api_instance.create_cluster_custom_object(
            group="cert-manager.io",
            version="v1",
            plural="clusterissuers",
            body=yaml.safe_load(yaml_content),
            pretty='true'
        )
        print("ClusterIssuer 'selfsigned' created successfully.")
    except ApiException as e:
        print("Error creating ClusterIssuer: %s\n" % e)

def main(args):
    yaml_filename = "selfsigned_cluster_issuer.yaml"

    if not os.path.exists(yaml_filename):
        cluster_issuer_yaml = create_cluster_issuer_yaml()

        # Save YAML file
        with open(yaml_filename, "w") as f:
            f.write(cluster_issuer_yaml)
        
        print(f"ClusterIssuer YAML file '{yaml_filename}' created successfully.")
    else:
        print(f"File '{yaml_filename}' already exists.")

    if args.submit:
        if os.path.exists(yaml_filename):
            with open(yaml_filename, 'r') as f:
                apply_yaml(f.read())
        else:
            print("No YAML file found to apply.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create and apply a self-signed cert-manager ClusterIssuer.")
    parser.add_argument("--submit", action="store_true", help="Apply the configuration to the cluster")
    args = parser.parse_args()
    main(args)
