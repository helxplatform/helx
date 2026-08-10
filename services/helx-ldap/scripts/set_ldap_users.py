#!/usr/bin/env python

from ldap3 import Server, Connection, ALL, MODIFY_ADD, MODIFY_REPLACE
from ldap3.core.exceptions import LDAPException
import yaml
import argparse
from urllib.parse import urlparse
import os

def load_ldap_config(config_file="helx_ldap_config.yaml"):
    """
    Load LDAP configuration from a YAML file if it exists.

    Args:
        config_file (str): Path to the YAML configuration file.

    Returns:
        dict: Dictionary of LDAP configuration data if the file exists, otherwise None.
    """

    if os.path.exists(config_file):
        with open(config_file, "r") as file:
            return yaml.safe_load(file)
    return None

def ensure_group_base_dn_exists(conn, group_base):
    """
    Ensure the group base DN exists in the LDAP directory. If it doesn't exist, create it.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_base (str): The base DN for the group.

    Returns:
        bool: True if the group base DN exists or is successfully created, False otherwise.
    """

    if not conn.search(group_base, '(objectClass=*)', search_scope='BASE'):
        attrs = {
            'objectClass': ['top', 'organizationalUnit'],
            'ou': group_base.split(',')[0].split('=')[1]
        }
        if conn.add(group_base, attributes=attrs):
            print(f"Created group base DN: {group_base}")
        else:
            print(f"Failed to create group base DN {group_base}: {conn.result['description']}")
            return False
    return True

def create_ldap_user(user, ldap_config):
    """
    Create or update an LDAP user and manage group memberships.

    This function creates a new LDAP user if they don't exist or updates the user's 
    attributes if they already exist. It also handles assigning the user to LDAP groups.

    Args:
        user (dict): Dictionary containing user details such as UID, CN, SN, and groups.
        ldap_config (dict): Dictionary containing LDAP configuration details such as 
                            LDAP server URL, bind DN, and base DNs.

    Returns:
        None
    """

    conn = None
    try:
        parsed_url = urlparse(ldap_config['ldap_server'])
        host = parsed_url.hostname
        port = parsed_url.port if parsed_url.port else (636 if parsed_url.scheme == 'ldaps' else 389)
        use_ssl = parsed_url.scheme == 'ldaps'

        # Connect to the LDAP server
        server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)
        conn = Connection(server, user=ldap_config['bind_dn'], password=ldap_config['bind_password'], auto_bind=True)

        # Ensure the group base DN exists
        group_base = ldap_config.get('group_base', 'ou=groups,dc=example,dc=org')
        if not ensure_group_base_dn_exists(conn, group_base):
            print(f"Cannot proceed without group base DN: {group_base}")
            return

        # Create or update the user
        user_dn = f"uid={user['uid']},{ldap_config['user_base']}"
        attrs = {
            'objectClass': ['inetOrgPerson', 'organizationalPerson', 'person', 'kubernetesSC', 'top'],
            'uid': user['uid'],
            'cn': user['cn'],
            'sn': user['sn'],
            'mail': user.get('email', ''),
            'telephoneNumber': user.get('telephoneNumber', ''),
            'o': user.get('o', ''),
            'ou': user.get('ou', ''),
            'givenName': user.get('givenName', ''),
            'displayName': user.get('displayName', ''),
            'supplementalGroups': [str(group) for group in user.get('supplementalGroups', [])],
            'runAsUser': str(user['runAsUser']),
            'runAsGroup': str(user['runAsGroup']),
            'fsGroup': str(user['fsGroup'])
        }

        # Check if the user already exists
        if conn.search(user_dn, '(objectClass=*)', search_scope='BASE', attributes=['*']):
            existing_entry = conn.entries[0]
            existing_attrs = existing_entry.entry_attributes_as_dict
            modifications = {}

            # Compare and update attributes
            for attr, new_value in attrs.items():
                existing_value = existing_attrs.get(attr, [])
                if isinstance(new_value, list):
                    if set(new_value) != set(existing_value):
                        modifications[attr] = [(MODIFY_REPLACE, new_value)]
                else:
                    if new_value != (existing_value[0] if existing_value else ''):
                        modifications[attr] = [(MODIFY_REPLACE, [new_value])]
            if modifications:
                if conn.modify(user_dn, modifications):
                    print(f"User {user['uid']} updated successfully.")
                else:
                    print(f"Failed to update user {user['uid']}: {conn.result['description']}")
            else:
                print(f"No updates necessary for user {user['uid']}.")
        else:
            if conn.add(user_dn, attributes=attrs):
                print(f"User {user['uid']} created successfully.")
            else:
                print(f"Failed to create user {user['uid']}: {conn.result['description']}")

        # Handle group memberships
        user_groups = user.get('groups', [])
        for group_name in user_groups:
            group_dn = f"cn={group_name},{group_base}"
            if not conn.search(group_dn, '(objectClass=groupOfNames)', search_scope='BASE', attributes=['member']):
                group_attrs = {'objectClass': ['groupOfNames', 'top'], 'cn': group_name, 'member': [user_dn]}
                if conn.add(group_dn, attributes=group_attrs):
                    print(f"Group {group_name} created and user {user['uid']} added as member.")
                else:
                    print(f"Failed to create group {group_name}: {conn.result['description']}")
            else:
                group_entry = conn.entries[0]
                if user_dn not in group_entry.member:
                    if conn.modify(group_dn, {'member': [(MODIFY_ADD, [user_dn])]}):
                        print(f"User {user['uid']} added to group {group_name}.")
                    else:
                        print(f"Failed to add user {user['uid']} to group {group_name}: {conn.result['description']}")
                else:
                    print(f"User {user['uid']} is already a member of group {group_name}.")

    except LDAPException as e:
        print(f"Error in creating user {user['uid']}: {e}")
    finally:
        if conn:
            conn.unbind()

def load_users_from_yaml(path):
    """
    Load user data from a YAML file.

    Args:
        path (str): Path to the YAML file.

    Returns:
        dict: Parsed user data from the YAML file.
    """

    with open(path, 'r') as file:
        return yaml.safe_load(file)

def main():
    """
    Main function to create LDAP users from a YAML file and manage their groups.

    Parses command-line arguments and processes each user entry from the YAML file.
    It uses command-line arguments or configuration file settings for the LDAP 
    server connection details.
    """

    parser = argparse.ArgumentParser(description='Create LDAP users from a YAML file.')
    parser.add_argument('yaml_file', help='Path to YAML file with user data')
    parser.add_argument('--ldap-server', help='LDAP server URL, e.g., ldap://localhost')
    parser.add_argument('--bind-dn', help='Bind DN for LDAP authentication')
    parser.add_argument('--bind-password', help='Password for Bind DN')
    parser.add_argument('--user-base', help='Base DN where the users will be created')
    parser.add_argument('--group-base', help='Base DN where the groups are located')

    args = parser.parse_args()

    # Load configuration from file, if available
    config = load_ldap_config()

    # Use command-line arguments or fallback to config file
    ldap_config = {
        'ldap_server': args.ldap_server or (config['ldap']['server_url'] if config else None),
        'bind_dn': args.bind_dn or (config['ldap']['admin']['bind_dn'] if config else 'cn=admin,dc=example,dc=org'),
        'bind_password': args.bind_password or (config['ldap']['admin']['password'] if config else None),
        'user_base': args.user_base or (config['ldap'].get('user_base') if config and 'user_base' in config['ldap'] else 'ou=users,dc=example,dc=org'),
        'group_base': args.group_base or (config['ldap'].get('group_base') if config and 'group_base' in config['ldap'] else 'ou=groups,dc=example,dc=org'),
    }

    if not ldap_config['ldap_server'] or not ldap_config['bind_password']:
        print("Error: LDAP server URL and bind password are required.")
        return

    users = load_users_from_yaml(args.yaml_file)
    for user in users['users']:
        create_ldap_user(user, ldap_config)

if __name__ == "__main__":
    main()
