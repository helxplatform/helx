#!/usr/bin/env python

from kubernetes import client, config
from kubernetes.client.rest import ApiException
import base64
import sys
import argparse
import os
import yaml
import time


def create_cert_manager_certificate(api_instance, namespace, cert_name):
    # Define the Certificate resource
    full_dns_name = "user-mutator." + namespace + ".svc"
    certificate = {
        "apiVersion": "cert-manager.io/v1",
        "kind": "Certificate",
        "metadata": {
            "name": cert_name,
            "namespace": namespace
        },
        "spec": {
            "secretName": cert_name + "-tls",
            "issuerRef": {
                "name": "selfsigned",  # Assuming 'selfsigned' ClusterIssuer is used
                "kind": "ClusterIssuer"
            },
            "commonName": full_dns_name,  # Set the Common Name
            "dnsNames": [full_dns_name]  # Set DNS names
        }
    }

    try:
        api_instance.create_namespaced_custom_object(
            group="cert-manager.io",
            version="v1",
            namespace=namespace,
            plural="certificates",
            body=certificate
        )
        print(f"Certificate '{cert_name}' created in namespace '{namespace}'")
    except ApiException as e:
        print(f"Error creating Certificate: {e}")

def get_kubernetes_ca_cert(core_v1_api, namespace):
    cert_name = "user-mutator-cert"

    # Use CustomObjectsApi for cert-manager Certificate
    custom_api_instance = client.CustomObjectsApi()

    # Check if Certificate already exists
    try:
        custom_api_instance.get_namespaced_custom_object(
            group="cert-manager.io",
            version="v1",
            namespace=namespace,
            plural="certificates",
            name=cert_name
        )
    except ApiException:
        # Certificate doesn't exist, create it
        create_cert_manager_certificate(custom_api_instance, namespace, cert_name)

    # Wait for the Secret to be created by cert-manager with exponential backoff
    secret_name = cert_name + "-tls"
    max_wait_time = 300  # Maximum wait time in seconds (5 minutes)
    attempt = 0
    wait_time = 1  # Start with 1 second
    start_time = time.time()

    while time.time() < start_time + max_wait_time:
        try:
            secret = core_v1_api.read_namespaced_secret(secret_name, namespace)
            ca_cert = secret.data['ca.crt']
            return ca_cert
        except ApiException:
            time.sleep(wait_time)
            attempt += 1
            wait_time *= 2  # Double the wait time for the next attempt

        if wait_time > 30:  # Cap the wait time at 30 seconds
            wait_time = 30

    raise RuntimeError(f"Secret '{secret_name}' not found in namespace '{namespace}' after waiting for 5 minutes.")

def create_mutating_webhook_configuration(namespace, ca_cert):
    webhook_configuration = client.V1MutatingWebhookConfiguration(
        api_version="admissionregistration.k8s.io/v1",
        kind="MutatingWebhookConfiguration",
        metadata=client.V1ObjectMeta(name="user-mutator-webhook"),
        webhooks=[client.V1MutatingWebhook(
            name="usermutator.k8s.io",
            client_config=client.AdmissionregistrationV1WebhookClientConfig(
                service=client.AdmissionregistrationV1ServiceReference(
                    namespace=namespace,
                    name="user-mutator",
                    path="/mutate",
                    port=8443
                ),
                ca_bundle=ca_cert
            ),
            failure_policy="Ignore",
            rules=[client.V1RuleWithOperations(
                operations=["CREATE", "UPDATE"],
                api_groups=["apps"],
                api_versions=["v1"],
                resources=["deployments"]  # Adjust as needed
            )],
            namespace_selector=client.V1LabelSelector(
                match_labels={"kubernetes.io/metadata.name": namespace}
            ),
            object_selector=client.V1LabelSelector(
                match_labels={"executor": "tycho"}
            ),
            side_effects="None",
            admission_review_versions=["v1"]
        )]
    )
    return webhook_configuration

def represent_none(self, _):
    return self.represent_scalar('tag:yaml.org,2002:null', '')

# Custom YAML dumper that skips null fields
def yaml_dump_skip_nulls(data):
    def skip_nulls(d):
        return {k: v for k, v in d.items() if v is not None}

    class SkipNullsYamlDumper(yaml.SafeDumper):
        def represent_mapping(self, tag, mapping, flow_style=None):
            return super().represent_mapping(tag, skip_nulls(mapping), flow_style)

    return yaml.dump(data, Dumper=SkipNullsYamlDumper, default_flow_style=False)

def save_to_yaml(webhook_configuration, filename):
    # Convert the Kubernetes object to a dictionary including its kind and metadata
    webhook_config_dict = client.ApiClient().sanitize_for_serialization(webhook_configuration)

    with open(filename, 'w') as file:
        yaml_content = yaml_dump_skip_nulls(webhook_config_dict)
        file.write(yaml_content)

def submit_to_cluster(webhook_configuration, api_instance):
    try:
        api_response = api_instance.create_mutating_webhook_configuration(webhook_configuration)
        print(f"MutatingWebhookConfiguration created: {api_response.metadata.name}")
    except client.rest.ApiException as e:
        print(f"Exception when submitting MutatingWebhookConfiguration: {e}")

def load_webhook_configuration_from_yaml(filename):
    with open(filename, 'r') as file:
        data = yaml.safe_load(file)
        # Extract the relevant parts for V1MutatingWebhookConfiguration
        webhook_config_data = {
            'metadata': data.get('metadata'),
            'webhooks': data.get('webhooks')
        }
        return client.V1MutatingWebhookConfiguration(**webhook_config_data)

def main(namespace, submit):
    config.load_kube_config()
    core_v1_api = client.CoreV1Api()
    ca_cert = get_kubernetes_ca_cert(core_v1_api, namespace)
    yaml_filename = f"{namespace}-mutating-webhook-configuration.yaml"

    if os.path.exists(yaml_filename):
        print(f"Using existing configuration from {yaml_filename}")
        webhook_configuration = load_webhook_configuration_from_yaml(yaml_filename)
    else:
        webhook_configuration = create_mutating_webhook_configuration(namespace, ca_cert)
        save_to_yaml(webhook_configuration, yaml_filename)

    if submit:
        admission_api = client.AdmissionregistrationV1Api()
        submit_to_cluster(webhook_configuration, admission_api)

yaml.add_representer(type(None), represent_none)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate and optionally submit a MutatingWebhookConfiguration.')
    parser.add_argument('namespace', type=str, help='The namespace for the webhook.')
    parser.add_argument('--submit', action='store_true', help='Submit the configuration to Kubernetes after generation.')
    args = parser.parse_args()
    main(args.namespace, args.submit)
