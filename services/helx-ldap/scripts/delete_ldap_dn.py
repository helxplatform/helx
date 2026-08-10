#!/usr/bin/env python

from ldap3 import Server, Connection, ALL
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
        dict or None: Loaded configuration as a dictionary, or None if the file doesn't exist.
    """

    if os.path.exists(config_file):
        with open(config_file, "r") as file:
            config = yaml.safe_load(file)
        return config
    else:
        return None

def delete_ldap_user(dn, ldap_config):
    """
    Delete a user from the LDAP server given the DN and configuration.
    
    Args:
        dn (str): The DN (Distinguished Name) of the LDAP entry to delete.
        ldap_config (dict): A dictionary containing LDAP server details, bind DN, and password.
    """

    conn = None
    try:
        # Parse the LDAP server URL
        parsed_url = urlparse(ldap_config['ldap_server'])
        host = parsed_url.hostname
        port = parsed_url.port
        use_ssl = parsed_url.scheme == 'ldaps'

        # Initialize the LDAP server
        server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)

        # Bind to the server
        conn = Connection(server, user=ldap_config['bind_dn'], password=ldap_config['bind_password'], auto_bind=True)

        # Attempt to delete the DN
        if conn.delete(dn):
            print(f"Successfully deleted DN: {dn}")
        else:
            if conn.result['description'] == 'noSuchObject':
                print(f"No such entry: {dn}")
            else:
                print(f"Error deleting DN {dn}: {conn.result['description']}")
    except Exception as e:
        print(f"LDAP error: {e}")
    finally:
        if conn:
            conn.unbind()

def main():
    """
    Main function to parse command-line arguments, load configuration, and delete the LDAP entry.
    
    This function accepts command-line arguments for the DN, LDAP server URL, bind DN, and bind password.
    If any of these values are missing from the arguments, the script attempts to load them from the helx_ldap_config.yaml file.
    """

    parser = argparse.ArgumentParser(description='Delete a single LDAP entry specified by DN.')
    parser.add_argument('dn', help='The DN of the LDAP entry to delete')
    parser.add_argument('--ldap-server', help='LDAP server URL, e.g., ldap://localhost')
    parser.add_argument('--bind-dn', default='cn=admin,dc=example,dc=org', help='Bind DN for LDAP authentication')
    parser.add_argument('--bind-password', help='Password for Bind DN')

    args = parser.parse_args()

    # Load the configuration from the YAML file, if it exists
    config = load_ldap_config()

    # Use values from the config file if available and not overridden by arguments
    ldap_config = {
        'ldap_server': args.ldap_server or (config['ldap'].get('server_url') if config and 'ldap' in config else None),
        'bind_dn': args.bind_dn or (config['ldap']['admin'].get('bind_dn') if config and 'admin' in config['ldap'] else 'cn=admin,dc=example,dc=org'),
        'bind_password': args.bind_password or (config['ldap']['admin'].get('password') if config and 'admin' in config['ldap'] else None),
    }

    # Check for missing required values
    if not ldap_config['ldap_server']:
        print("Error: LDAP server URL is required.")
        return
    if not ldap_config['bind_password']:
        print("Error: LDAP bind password is required.")
        return

    # Delete the LDAP user
    delete_ldap_user(args.dn, ldap_config)

if __name__ == "__main__":
    main()
