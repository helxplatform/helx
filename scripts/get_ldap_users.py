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

def connect_to_ldap(ldap_server_url, bind_dn, bind_password):
    """
    Establishes a connection to the LDAP server.

    Args:
        ldap_server_url (str): LDAP server URL.
        bind_dn (str): Bind DN for LDAP authentication.
        bind_password (str): Password for Bind DN.

    Returns:
        ldap3.Connection: An active LDAP connection.
    """
    parsed_url = urlparse(ldap_server_url)
    host = parsed_url.hostname
    port = parsed_url.port if parsed_url.port else (636 if parsed_url.scheme == 'ldaps' else 389)
    use_ssl = parsed_url.scheme == 'ldaps'

    # Initialize and bind to the LDAP server
    server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)
    conn = Connection(server, user=bind_dn, password=bind_password, auto_bind=True)
    return conn

def fetch_all_users(conn, search_base):
    """
    Fetches all user entries from the LDAP directory.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        search_base (str): The base DN for searching user entries.

    Returns:
        list: A list of ldap3.Entry objects representing user entries.
    """
    search_filter = '(|(objectClass=inetOrgPerson)(objectClass=posixAccount))'
    retrieve_attributes = [
        'uid', 'cn', 'sn', 'mail', 'telephoneNumber',
        'givenName', 'displayName', 'o', 'ou',
        'runAsUser', 'runAsGroup', 'fsGroup', 'supplementalGroups',
        'uidNumber', 'gidNumber', 'homeDirectory', 'loginShell'
    ]

    conn.search(search_base, search_filter, search_scope=SUBTREE, attributes=retrieve_attributes)
    return conn.entries

def fetch_posix_groups(conn, group_base):
    """
    Fetches all posixGroup entries and builds a mapping of uid to posixGroups.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_base (str): The base DN for searching group entries.

    Returns:
        dict: A mapping of user uid to a list of posixGroup names.
    """
    conn.search(
        search_base=group_base,
        search_filter='(objectClass=posixGroup)',
        search_scope=SUBTREE,
        attributes=['cn', 'memberUid']
    )
    posix_group_entries = conn.entries

    uid_to_posix_groups = {}
    for group_entry in posix_group_entries:
        group_name = group_entry.cn.value
        member_uids = group_entry.memberUid.values if 'memberUid' in group_entry else []
        for uid in member_uids:
            uid_to_posix_groups.setdefault(uid, []).append(group_name)
    return uid_to_posix_groups

def fetch_group_of_names(conn, group_base):
    """
    Fetches all groupOfNames entries and builds a mapping of user_dn to groups.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_base (str): The base DN for searching group entries.

    Returns:
        dict: A mapping of user DN to a list of group names.
    """
    conn.search(
        search_base=group_base,
        search_filter='(objectClass=groupOfNames)',
        search_scope=SUBTREE,
        attributes=['cn', 'member']
    )
    group_of_names_entries = conn.entries

    dn_to_groups = {}
    for group_entry in group_of_names_entries:
        group_name = group_entry.cn.value
        members = group_entry.member.values if 'member' in group_entry else []
        for dn in members:
            dn_to_groups.setdefault(dn, []).append(group_name)
    return dn_to_groups

def process_user_entries(user_entries, uid_to_posix_groups, dn_to_groups):
    """
    Processes user entries and assigns group memberships.

    Args:
        user_entries (list): A list of ldap3.Entry objects representing user entries.
        uid_to_posix_groups (dict): Mapping of uid to posixGroup names.
        dn_to_groups (dict): Mapping of user DN to group names.

    Returns:
        list: A list of dictionaries containing processed user details.
    """
    retrieve_attributes = [
        'uid', 'cn', 'sn', 'mail', 'telephoneNumber',
        'givenName', 'displayName', 'o', 'ou',
        'runAsUser', 'runAsGroup', 'fsGroup', 'supplementalGroups',
        'uidNumber', 'gidNumber', 'homeDirectory', 'loginShell'
    ]

    result_set = []
    for entry in user_entries:
        entry_dict = entry.entry_attributes_as_dict
        processed_entry = {}

        # Process each attribute and handle missing attributes
        for attr in retrieve_attributes:
            if attr in entry_dict and entry_dict[attr]:
                if attr in ['runAsUser', 'runAsGroup', 'fsGroup', 'uidNumber', 'gidNumber']:
                    processed_entry[attr] = int(entry_dict[attr][0])
                elif attr == 'supplementalGroups':
                    processed_entry[attr] = [int(x) for x in entry_dict[attr]]
                else:
                    processed_entry[attr] = entry_dict[attr][0]
            else:
                # Assign default values for certain attributes
                if attr in ['uidNumber', 'gidNumber']:
                    processed_entry[attr] = None
                elif attr == 'supplementalGroups':
                    processed_entry[attr] = []
                else:
                    processed_entry[attr] = ""

        # Assign posixGroup memberships
        uid = processed_entry['uid']
        posix_groups = uid_to_posix_groups.get(uid, [])
        processed_entry['posixGroups'] = posix_groups

        # Assign groupOfNames memberships
        user_dn = entry.entry_dn
        groups = dn_to_groups.get(user_dn, [])
        processed_entry['groups'] = groups

        result_set.append(processed_entry)
    return result_set

def fetch_user_details(ldap_server_url, bind_dn, bind_password, search_base, group_base):
    """
    Orchestrates the fetching and processing of user details.

    Args:
        ldap_server_url (str): The URL of the LDAP server.
        bind_dn (str): The distinguished name used for binding to the LDAP server.
        bind_password (str): The password used for the bind DN.
        search_base (str): The base DN for searching user entries.
        group_base (str): The base DN for searching group entries.

    Returns:
        list: A list of dictionaries, each containing user details and their group memberships.
    """
    conn = None
    try:
        conn = connect_to_ldap(ldap_server_url, bind_dn, bind_password)

        # Fetch user entries
        user_entries = fetch_all_users(conn, search_base)
        if not user_entries:
            print(f"No users found in search base: {search_base}")
            return []

        # Fetch group memberships
        uid_to_posix_groups = fetch_posix_groups(conn, group_base)
        dn_to_groups = fetch_group_of_names(conn, group_base)

        # Process user entries
        result_set = process_user_entries(user_entries, uid_to_posix_groups, dn_to_groups)
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
                if key in ['groups', 'posixGroups']:
                    print(f"{key}: {', '.join(value)}")
                else:
                    print(f"{key}: {value}")
            print("-" * 40)

if __name__ == "__main__":
    main()
