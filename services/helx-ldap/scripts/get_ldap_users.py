#!/usr/bin/env python

import traceback
from ldap3 import Server, Connection, ALL, SUBTREE
import argparse
import yaml
from urllib.parse import urlparse
import os

def load_ldap_config(config_file="helx_ldap_config.yaml"):
    """
    Load LDAP configuration from a YAML file, if it exists.

    Args:
        config_file (str): Path to the YAML configuration file (default: helx_ldap_config.yaml).

    Returns:
        dict or None: Returns a dictionary of LDAP configuration if the file exists, 
        otherwise returns None.
    """
    if os.path.exists(config_file):
        with open(config_file, "r") as file:
            return yaml.safe_load(file)
    return None

def fetch_user_details(ldap_server_url, bind_dn, bind_password, search_base, group_base):
    """
    Fetches user details from the LDAP server and processes their attributes.

    The function binds to an LDAP server and retrieves user entries based on 
    the specified search base and filter. It also checks group memberships for 
    each user and processes attributes like `cn`, `mail`, `telephoneNumber`, etc.

    Args:
        ldap_server_url (str): The URL of the LDAP server (e.g., ldap://localhost).
        bind_dn (str): The distinguished name (DN) used for binding to the LDAP server.
        bind_password (str): The password used for the bind DN.
        search_base (str): The base DN for searching user entries.
        group_base (str): The base DN for searching group memberships.

    Returns:
        list: A list of dictionaries, each containing user details and their group memberships.
    """
    conn = None
    try:
        parsed_url = urlparse(ldap_server_url)
        host = parsed_url.hostname
        port = parsed_url.port
        use_ssl = parsed_url.scheme == 'ldaps'

        # Initialize and bind to the LDAP server
        server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)
        conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)

        # Search for user entries
        search_filter = '(objectClass=inetOrgPerson)'
        retrieve_attributes = [
            'uid', 'cn', 'sn', 'mail', 'telephoneNumber',
            'givenName', 'displayName', 'o', 'ou',
            'runAsUser', 'runAsGroup', 'fsGroup', 'supplementalGroups'
        ]

        # Check if the search base exists
        base_check = conn.search(search_base, '(objectClass=*)', search_scope=SUBTREE, attributes=[])
        if not base_check:
            print(f"Search base '{search_base}' does not exist.")
            return []

        # Search for users and process the results
        conn.search(search_base, search_filter, search_scope=SUBTREE, attributes=retrieve_attributes)

        # Return an empty list if no users are found
        if len(conn.entries) == 0:
            print(f"No users found in search base: {search_base}")
            return []

        result_set = []
        for entry in conn.entries:
            entry_dict = entry.entry_attributes_as_dict
            processed_entry = {}

            # Process each attribute and handle missing attributes
            for attr in retrieve_attributes:
                if attr in entry_dict and entry_dict[attr]:
                    if attr in ['runAsUser', 'runAsGroup', 'fsGroup']:
                        processed_entry[attr] = int(entry_dict[attr][0])
                    elif attr == 'supplementalGroups':
                        processed_entry[attr] = [int(x) for x in entry_dict[attr]]
                    else:
                        processed_entry[attr] = entry_dict[attr][0]
                else:
                    processed_entry[attr] = ""

            # Fetch group memberships for the user
            user_dn = entry.entry_dn
            conn.search(
                search_base=group_base,
                search_filter=f'(&(objectClass=groupOfNames)(member={user_dn}))',
                search_scope=SUBTREE,
                attributes=['cn']
            )

            # Process group memberships
            group_names = [g_entry.cn.value for g_entry in conn.entries] if conn.entries else []
            processed_entry['groups'] = group_names

            result_set.append(processed_entry)

        return result_set
    except Exception as e:
        print(f"LDAP error: {e}")
        traceback.print_exc()
        return []
    finally:
        if conn:
            conn.unbind()

def main():
    """
    Main function to retrieve and display user details from the LDAP directory.

    This function parses command-line arguments for LDAP connection details,
    binds to the LDAP server, retrieves user details, and outputs them in either
    text or YAML format.

    Args:
        None

    Returns:
        None
    """
    parser = argparse.ArgumentParser(description='Retrieve and display details for all users in the LDAP directory.')
    parser.add_argument('--ldap-server', help='LDAP server URL, e.g., ldap://localhost')
    parser.add_argument('--bind-dn', help='Bind DN for LDAP authentication')
    parser.add_argument('--bind-password', help='Password for Bind DN')
    parser.add_argument('--search-base', default='ou=users,dc=example,dc=org', help='Base DN where the search starts')
    parser.add_argument('--group-base', default='ou=groups,dc=example,dc=org', help='Base DN where the groups are located')
    parser.add_argument('--output-format', choices=['text', 'yaml'], default='text', help='Output format of the user data')

    args = parser.parse_args()

    # Load configuration from the YAML file, if available
    config = load_ldap_config()

    # Use values from the config file if available, otherwise leave as None
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

    # Fetch user details
    users = fetch_user_details(
        ldap_server_url,
        bind_dn,
        bind_password,
        args.search_base,
        args.group_base
    )

    # Output the user details in the requested format
    if args.output_format == 'yaml':
        print(yaml.dump({'users': users}, default_flow_style=False))
    else:
        for user in users:
            print("User Details:")
            for key, value in user.items():
                if key == 'groups':
                    print(f"{key}: {', '.join(value)}")
                else:
                    print(f"{key}: {value}")
            print("-" * 40)

if __name__ == "__main__":
    main()
