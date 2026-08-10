#!/usr/bin/env python

from cryptography import x509
from cryptography.hazmat.backends import default_backend
import base64
import os
import argparse
from kubernetes import client, config

def extract_cert_from_secret(namespace, secret_name):
    config.load_kube_config()

    api_instance = client.CoreV1Api()

    try:
        secret = api_instance.read_namespaced_secret(secret_name, namespace)
        cert_data = secret.data.get('tls.crt')
        if cert_data is None:
            raise ValueError("Certificate data not found in the secret.")

        cert_bytes = base64.b64decode(cert_data)
        cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())

        print_certificate(cert)
    except client.exceptions.ApiException as e:
        print(f"An error occurred: {e}")

def print_certificate(cert):
    print("Certificate Details:")
    print(f"Subject: {cert.subject}")
    common_names = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    if common_names:
        print(f"Common Name: {common_names[0].value}")

    try:
        san_extension = cert.extensions.get_extension_for_oid(x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        san_names = san_extension.value
        print("Subject Alternative Names:")
        for name in san_names:
            print(f"  {name}")
    except x509.ExtensionNotFound:
        print("No Subject Alternative Name extension.")

    print(f"Issuer: {cert.issuer}")
    print(f"Validity: {cert.not_valid_before} - {cert.not_valid_after}")
    print(f"Serial Number: {cert.serial_number}")
    print(f"Version: {cert.version}")
    # Add more fields as needed

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract certificate from a Kubernetes secret.")
    parser.add_argument("namespace", type=str, help="The namespace where the secret is located.")
    parser.add_argument("secret_name", type=str, help="The name of the secret.")

    args = parser.parse_args()

    extract_cert_from_secret(args.namespace, args.secret_name)
