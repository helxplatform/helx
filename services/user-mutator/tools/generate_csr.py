#!/usr/bin/env python

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import base64
import sys
import os
import time
import argparse



def parse_arguments():
    parser = argparse.ArgumentParser(description='Generate and optionally submit a CSR for a Kubernetes webhook.')
    parser.add_argument('namespace', type=str, help='The namespace for the webhook.')
    parser.add_argument('webhook_name', type=str, help='The name of the webhook.')
    parser.add_argument('--submit', action='store_true', help='Submit the CSR to Kubernetes after generation.')
    return parser.parse_args()

def generate_csr(namespace, webhook_name):
    key_file_path = f"{webhook_name}_key.pem"
    csr_file_path = f"{webhook_name}_csr.pem"

    # Check if the files already exist
    if os.path.exists(key_file_path) and os.path.exists(csr_file_path):
        print(f"Key and CSR files already exist for {webhook_name}.")
        return key_file_path, csr_file_path, False

    # Generate a private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Generate a CSR
    csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"{webhook_name}.{namespace}.svc"),
    ])).sign(private_key, hashes.SHA256())

    with open(key_file_path, "wb") as key_file:
        key_file.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    with open(csr_file_path, "wb") as csr_file:
        csr_file.write(csr.public_bytes(serialization.Encoding.PEM))

    return key_file_path, csr_file_path, True

def submit_csr(api_instance,csr_file_path, webhook_name):
    # Read the CSR file
    with open(csr_file_path, "rb") as f:
        csr_data = f.read()

    # Encode CSR data in base64
    csr_base64 = base64.b64encode(csr_data).decode('utf-8')

    # Create a CertificateSigningRequest object
    csr_object = client.V1CertificateSigningRequest(
        metadata=client.V1ObjectMeta(name=webhook_name),
        spec=client.V1CertificateSigningRequestSpec(
            request=csr_base64,
            #usages=["client auth", "digital signature", "key encipherment"],
            usages=["client auth", "server auth", "digital signature", "key encipherment"],
            #signer_name="kubernetes.io/kube-apiserver-client"  # Specify the appropriate signerName here
            #signer_name="kubernetes.io/kublet-serving"  # For webhook
            signer_name="kubernetes.io/kube-apiserver"  # Specify the appropriate signerName here
        )
    )

    # Submit the CSR
    try:
        api_response = api_instance.create_certificate_signing_request(csr_object)
        print(f"CSR submitted successfully: {api_response.metadata.name}")
        return True
    except ApiException as e:
        print(f"Exception when calling CertificatesV1Api->create_certificate_signing_request: {e}")
        return False

def get_signed_certificate(api_instance, csr_name):
    try:
        csr = api_instance.read_certificate_signing_request(csr_name)
        print(csr)
        if csr.status.certificate:
            certificate = base64.b64decode(csr.status.certificate).decode('utf-8')
            print(f"Successfully retrieved signed certificate for CSR {csr_name}.")
            return certificate
        else:
            print(f"No signed certificate found for CSR {csr_name}.")
            return None
    except ApiException as e:
        print(f"Exception when calling CertificatesV1Api->read_certificate_signing_request: {e}")
        return None

def wait_for_approval(api_instance, csr_name, timeout=300):
    start_time = time.time()
    while True:
        time.sleep(10)  # Poll every 10 seconds
        try:
            csr = api_instance.read_certificate_signing_request_status(csr_name)
            if csr.status.conditions:
                for condition in csr.status.conditions:
                    if condition.type == "Approved":
                        print(f"CSR {csr_name} approved.")
                        return True
        except ApiException as e:
            print(f"Exception when calling CertificatesV1Api->read_certificate_signing_request_status: {e}")
            return False
        
        if time.time() - start_time > timeout:
            print(f"Timeout waiting for CSR {csr_name} approval.")
            return False

if __name__ == "__main__":
    args = parse_arguments()

    key_file_path, csr_file_path, did_generate = generate_csr(args.namespace, args.webhook_name)
    if did_generate:  print(f"CSR and private key for {args.webhook_name} in namespace {args.namespace} generated successfully.")

    if args.submit:
        # Load Kubernetes config
        config.load_kube_config()
        api_instance = client.CertificatesV1Api()

        if submit_csr(api_instance, csr_file_path, args.webhook_name):
            if wait_for_approval(api_instance, args.webhook_name):
                signed_cert = get_signed_certificate(api_instance, args.webhook_name)
                if signed_cert:
                    with open(f"{args.webhook_name}_cert.pem", "w") as cert_file:
                        cert_file.write(signed_cert)
