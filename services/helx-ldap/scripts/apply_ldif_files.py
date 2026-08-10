#!/usr/bin/env python

import os
import subprocess
import argparse
import yaml

def load_ldap_config(config_file="helx_ldap_config.yaml"):
    """
    Load LDAP configuration from a YAML file.

    Args:
        config_file (str): Path to the YAML configuration file (default: helx_ldap_config.yaml).

    Returns:
        dict: A dictionary containing the LDAP configuration data loaded from the file.
    """

    with open(config_file, "r") as file:
        return yaml.safe_load(file)

def apply_ldif_file(ldif_file, ldap_server_url, config_dn, config_password):
    """
    Apply a single LDIF file using the ldapmodify command.

    Args:
        ldif_file (str): The path to the LDIF file to be applied.
        ldap_server_url (str): The URL of the LDAP server (e.g., ldap://localhost).
        config_dn (str): The distinguished name (DN) used for binding to the LDAP server.
        config_password (str): The password for the DN used for binding.

    Raises:
        CalledProcessError: If the ldapmodify command fails.
    """

    ldapmodify_cmd = [
        "ldapmodify",
        "-H", ldap_server_url,
        "-D", config_dn,
        "-w", config_password,
        "-f", ldif_file
    ]

    try:
        print(f"Applying LDIF: {ldif_file}...")
        subprocess.run(ldapmodify_cmd, check=True)
        print(f"LDIF {ldif_file} applied successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error applying {ldif_file}: {e}")

def apply_ldif_directory_bottom_up(ldif_root):
    """
    Traverse a directory tree in bottom-up order and apply all LDIF files.

    This function loads the LDAP configuration from the helx_ldap_config.yaml file and 
    applies all `.ldif` files in the given directory, processing subdirectories first.

    Args:
        ldif_root (str): The root directory containing LDIF files to be applied.
    """

    # Load LDAP configuration
    config = load_ldap_config()

    # Extract relevant fields from the configuration file
    ldap_server_url = config['ldap']['server_url']
    config_dn = config['ldap']['config']['dn']
    config_password = config['ldap']['config']['password']

    # Traverse the directory tree in bottom-up order
    for root, dirs, files in os.walk(ldif_root, topdown=False):
        for file in files:
            if file.endswith(".ldif"):
                ldif_path = os.path.join(root, file)
                apply_ldif_file(ldif_path, ldap_server_url, config_dn, config_password)

if __name__ == "__main__":
    # Argument parser setup
    parser = argparse.ArgumentParser(description="Apply LDIF files from a directory in bottom-up order.")
    parser.add_argument("directory", help="The root directory containing LDIF files to apply.")

    # Parse arguments
    args = parser.parse_args()

    # Apply all LDIF files in the specified directory (bottom-up)
    apply_ldif_directory_bottom_up(args.directory)
