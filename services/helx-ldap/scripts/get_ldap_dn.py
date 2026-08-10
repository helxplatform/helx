#!/usr/bin/env python

"""
Script to retrieve all Distinguished Names (DNs) from an LDAP server.

This script connects to an LDAP server using credentials (either from the 
command-line arguments or from the optional helx_ldap_config.yaml file) and 
fetches all DNs under a specified search base. The search base can be provided 
as a command-line argument with a default fallback.
"""

from ldap3 import Server, Connection, ALL, SUBTREE
import argparse
from urllib.parse import urlparse
import os
import yaml

def load_ldap_config(config_file="helx_ldap_config.yaml"):
    """
    Load LDAP configuration from a YAML file, if it exists.

    Args:
        config_file (str): Path to the configuration file (default: helx_ldap_config.yaml)

    Returns:
        dict or None: The loaded configuration as a dictionary, or None if the file doesn't exist.
    """

    if os.path.exists(config_file):
        with open(config_file, "r") as file:
            config = yaml.safe_load(file)
        return config
    else:
        return None

def fetch_all_dns(ldap_server_url, bind_dn, bind_password, search_base):
    """
    Connect to an LDAP server and retrieve all Distinguished Names (DNs) from the specified search base.

    Args:
        ldap_server_url (str): The URL of the LDAP server (e.g., ldap://localhost).
        bind_dn (str): The Distinguished Name (DN) to bind to the LDAP server.
        bind_password (str): The password for the bind DN.
        search_base (str): The base DN where the search begins.

    Returns:
        list: A list of DNs retrieved from the server, or an empty list in case of an error.
    """

    conn = None
    try:
        # Parse the LDAP server URL and extract the host, port, and SSL setting
        parsed_url = urlparse(ldap_server_url)
        host = parsed_url.hostname
        port = parsed_url.port
        use_ssl = parsed_url.scheme == 'ldaps'

        # Initialize the LDAP server and establish the connection
        server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)
        conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
        
        # Define the search filter to match all entries (objectClass=*)
        search_filter = '(objectClass=*)'

        # Perform the search operation
        conn.search(search_base, search_filter, search_scope=SUBTREE, attributes=[])

        # Extract and return the DNs from the result set
        result_set = [entry.entry_dn for entry in conn.entries]
        return result_set
    except Exception as e:
        print("LDAP error:", e)
        return []
    finally:
        if conn:
            conn.unbind()

def main():
    """
    Main function to parse arguments, load configuration, and retrieve DNs.

    The function accepts command-line arguments for the LDAP server URL, bind DN, 
    bind password, and search base. It also optionally loads configurations from 
    the helx_ldap_config.yaml file if present.
    """

    parser = argparse.ArgumentParser(description='Retrieve all Distinguished Names (DNs) from an LDAP server.')
    
    # Command-line arguments
    parser.add_argument('--ldap-server', help='LDAP server URL, e.g., ldap://localhost')
    parser.add_argument('--bind-dn', help='Bind DN for LDAP authentication')
    parser.add_argument('--bind-password', help='Password for Bind DN')
    parser.add_argument('--search-base', default='dc=example,dc=org', help='Base DN where the search starts (default: dc=example,dc=org)')

    args = parser.parse_args()

    # Load configuration from the helx_ldap_config.yaml file if available
    config = load_ldap_config()

    # Use either command-line arguments or configuration file for connection details
    ldap_server_url = args.ldap_server or (config['ldap'].get('server_url') if config and 'ldap' in config else None)
    bind_dn = args.bind_dn or (config['ldap']['admin'].get('bind_dn') if config and 'admin' in config['ldap'] else 'cn=admin,dc=example,dc=org')
    bind_password = args.bind_password or (config['ldap']['admin'].get('password') if config and 'admin' in config['ldap'] else None)

    # Ensure mandatory parameters are provided
    if not ldap_server_url:
        print("Error: LDAP server URL is required.")
        return
    if not bind_password:
        print("Error: LDAP bind password is required.")
        return

    # Fetch and print all DNs from the LDAP server
    dns = fetch_all_dns(ldap_server_url, bind_dn, bind_password, args.search_base)
    for dn in dns:
        print(dn)

if __name__ == "__main__":
    main()
