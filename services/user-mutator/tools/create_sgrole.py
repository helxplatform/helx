#!/usr/bin/env python

from kubernetes import client, config
from kubernetes.client.rest import ApiException
import argparse
import os
import yaml


def generate_yaml(sa_name, namespace):
    yaml_content = f"""
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: {namespace}
  name: sgclusters-role
rules:
- apiGroups: ["stackgres.io"]
  resources: ["sgclusters", "sgpoolconfigs", "sgpgconfigs", "sginstanceprofiles", "sgscripts"]
  verbs: ["create", "get", "list", "watch", "delete", "patch"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: sgclusters-role-binding
  namespace: {namespace}
subjects:
- kind: ServiceAccount
  name: {sa_name}
  namespace: {namespace}
roleRef:
  kind: Role
  name: sgclusters-role
  apiGroup: rbac.authorization.k8s.io
"""
    return yaml_content

def apply_configuration(file_path):
    config.load_kube_config()

    with open(file_path, 'r') as f:
        yml_document_all = yaml.safe_load_all(f)

        for yml_document in yml_document_all:
            kind = yml_document['kind']
            namespace = yml_document['metadata']['namespace']
            name = yml_document['metadata']['name']

            try:
                rbac_api = client.RbacAuthorizationV1Api()

                if kind == 'Role':
                    try:
                        existing_role = rbac_api.read_namespaced_role(name, namespace)
                        if existing_role:
                            rbac_api.replace_namespaced_role(name, namespace, yml_document)
                            print(f"Role '{name}' updated in namespace '{namespace}'.")
                    except ApiException as e:
                        if e.status == 404:
                            rbac_api.create_namespaced_role(namespace, yml_document)
                            print(f"Role '{name}' created in namespace '{namespace}'.")
                        else:
                            raise e

                elif kind == 'RoleBinding':
                    try:
                        existing_role_binding = rbac_api.read_namespaced_role_binding(name, namespace)
                        if existing_role_binding:
                            rbac_api.replace_namespaced_role_binding(name, namespace, yml_document)
                            print(f"RoleBinding '{name}' updated in namespace '{namespace}'.")
                    except ApiException as e:
                        if e.status == 404:
                            rbac_api.create_namespaced_role_binding(namespace, yml_document)
                            print(f"RoleBinding '{name}' created in namespace '{namespace}'.")
                        else:
                            raise e

                else:
                    print(f"Unsupported kind: {kind}")

            except ApiException as e:
                print(f"Exception when calling Kubernetes API: {e}")

def main():
    parser = argparse.ArgumentParser(description="Generate and optionally apply a Kubernetes Role and RoleBinding for a service account.")
    parser.add_argument("service_account", help="Name of the service account")
    parser.add_argument("namespace", help="Kubernetes namespace")
    parser.add_argument("--submit", action="store_true", help="Apply the configuration using Kubernetes Python client")
    
    args = parser.parse_args()
    file_name = f"{args.namespace}_{args.service_account}_role_binding.yaml"

    if not os.path.exists(file_name):
        yaml_content = generate_yaml(args.service_account, args.namespace)
        with open(file_name, 'w') as file:
            file.write(yaml_content)
        print(f"Generated YAML file: {file_name}")
    else:
        print(f"Using existing YAML file: {file_name}")

    if args.submit:
        print("Applying configuration...")
        apply_configuration(file_name)

if __name__ == "__main__":
    main()
