#!/usr/bin/env python

import argparse
from kubernetes import client, config
import base64
from cryptography import x509
from cryptography.hazmat.backends import default_backend

def extract_ca_cert_from_secret(namespace, secret_name):
    config.load_kube_config()

    api_instance = client.CoreV1Api()

    try:
        secret = api_instance.read_namespaced_secret(secret_name, namespace)
        ca_cert_data = secret.data.get('ca.crt')
        if ca_cert_data is None:
            raise ValueError("CA certificate data not found in the secret.")

        ca_cert_bytes = base64.b64decode(ca_cert_data)
        ca_cert = x509.load_pem_x509_certificate(ca_cert_bytes, default_backend())

        print_certificate(ca_cert)
    except client.exceptions.ApiException as e:
        print(f"An error occurred: {e}")

def print_certificate(cert):
    print("Certificate Details:")
    print(f"Subject: {cert.subject}")
    print(f"Issuer: {cert.issuer}")
    print(f"Validity: {cert.not_valid_before} - {cert.not_valid_after}")
    print(f"Serial Number: {cert.serial_number}")
    print(f"Version: {cert.version}")
    # Add more fields as needed

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract CA certificate from a Kubernetes secret.")
    parser.add_argument("namespace", type=str, help="The namespace where the secret is located.")
    parser.add_argument("secret_name", type=str, help="The name of the secret.")

    args = parser.parse_args()

    extract_ca_cert_from_secret(args.namespace, args.secret_name)
