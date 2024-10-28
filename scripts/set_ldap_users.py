#!/usr/bin/env python

from ldap3 import Server, Connection, ALL, MODIFY_ADD, MODIFY_REPLACE, SUBTREE
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

def connect_to_ldap(ldap_config):
    """
    Establishes a connection to the LDAP server.

    Args:
        ldap_config (dict): LDAP configuration details.

    Returns:
        ldap3.Connection: An active LDAP connection.
    """
    parsed_url = urlparse(ldap_config['ldap_server'])
    host = parsed_url.hostname
    port = parsed_url.port if parsed_url.port else (636 if parsed_url.scheme == 'ldaps' else 389)
    use_ssl = parsed_url.scheme == 'ldaps'

    # Connect to the LDAP server
    server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)
    conn = Connection(
        server,
        user=ldap_config['bind_dn'],
        password=ldap_config['bind_password'],
        auto_bind=True
    )
    return conn

def ensure_group_base_dn_exists(conn, group_base):
    """
    Ensures that the group base DN exists in the LDAP directory.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_base (str): The group base DN.

    Returns:
        bool: True if the group base DN exists or was created successfully.
    """
    if conn.search(group_base, '(objectClass=*)', search_scope='BASE'):
        return True
    else:
        # Attempt to create the group base DN
        dn_components = group_base.split(',')
        for i in range(len(dn_components), 0, -1):
            dn = ','.join(dn_components[:i])
            if conn.search(dn, '(objectClass=*)', search_scope='BASE'):
                break
            else:
                # Create the missing DN component
                attrs = {'objectClass': 'organizationalUnit', 'ou': dn_components[i-1][3:]}
                if not conn.add(dn, attributes=attrs):
                    print(f"Failed to create DN {dn}: {conn.result['description']}")
                    return False
        return True

def prepare_user_attributes(user):
    """
    Prepares the user attributes for LDAP entry.

    Args:
        user (dict): User details.

    Returns:
        dict: A dictionary of user attributes.
    """
    # Ensure 'runAsUser' and 'runAsGroup' are present
    if 'runAsUser' not in user or 'runAsGroup' not in user:
        raise ValueError(f"'runAsUser' and 'runAsGroup' must be provided for user {user['uid']}")

    # Set 'uidNumber' and 'gidNumber' if not present
    user['uidNumber'] = user.get('uidNumber', user['runAsUser'])
    user['gidNumber'] = user.get('gidNumber', user['runAsGroup'])

    # Ensure 'homeDirectory' and 'loginShell' are set
    user['homeDirectory'] = user.get('homeDirectory', f"/home/{user['uid']}")
    user['loginShell'] = user.get('loginShell', '/bin/bash')

    attrs = {
        'objectClass': [
            'inetOrgPerson',
            'organizationalPerson',
            'person',
            'posixAccount',
            'kubernetesSC',
            'top'
        ],
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
        'fsGroup': str(user['fsGroup']),
        'uidNumber': str(user['uidNumber']),
        'gidNumber': str(user['gidNumber']),
        'homeDirectory': user['homeDirectory'],
        'loginShell': user['loginShell'],
    }
    return attrs

def create_or_update_user(conn, user_dn, attrs):
    """
    Creates a new LDAP user or updates an existing one.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        user_dn (str): The distinguished name of the user.
        attrs (dict): The user's attributes.

    Returns:
        None
    """
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
                print(f"User {attrs['uid']} updated successfully.")
            else:
                print(f"Failed to update user {attrs['uid']}: {conn.result['description']}")
        else:
            print(f"No updates necessary for user {attrs['uid']}.")
    else:
        if conn.add(user_dn, attributes=attrs):
            print(f"User {attrs['uid']} created successfully.")
        else:
            print(f"Failed to create user {attrs['uid']}: {conn.result['description']}")

def get_existing_posix_groups(conn, group_base):
    """
    Retrieves existing posixGroup entries from LDAP.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_base (str): The group base DN.

    Returns:
        dict: A mapping of group names to their gidNumbers.
    """
    group_gid_map = {}
    conn.search(
        search_base=group_base,
        search_filter='(objectClass=posixGroup)',
        search_scope=SUBTREE,
        attributes=['cn', 'gidNumber']
    )
    for entry in conn.entries:
        group_name = entry.cn.value
        gid_number = int(entry.gidNumber.value)
        group_gid_map[group_name] = gid_number
    return group_gid_map

def handle_posix_group_memberships(conn, user, group_base, group_gid_map):
    """
    Handles posixGroup memberships for the user.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        user (dict): User details.
        group_base (str): The group base DN.
        group_gid_map (dict): Mapping of group names to gidNumbers.

    Returns:
        None
    """
    # Find the next available gidNumber
    if group_gid_map:
        next_gid_number = max(group_gid_map.values()) + 1
    else:
        next_gid_number = 1000  # Starting gidNumber for groups

    posix_groups = user.get('posixGroups', [])
    for group_name in posix_groups:
        group_dn = f"cn={group_name},{group_base}"

        # Check if the group exists
        if group_name in group_gid_map:
            gid_number = group_gid_map[group_name]
            group_exists = True
        else:
            gid_number = next_gid_number
            next_gid_number += 1
            group_gid_map[group_name] = gid_number
            group_exists = False

        if not group_exists:
            # Create the posixGroup
            group_attrs = {
                'objectClass': ['posixGroup', 'top'],
                'cn': group_name,
                'gidNumber': str(gid_number),
                'memberUid': [user['uid']]
            }
            if conn.add(group_dn, attributes=group_attrs):
                print(f"Posix group {group_name} created with gidNumber {gid_number} and user {user['uid']} added as member.")
            else:
                print(f"Failed to create posix group {group_name}: {conn.result['description']}")
        else:
            # Group exists, check if user is a member
            if conn.search(group_dn, '(objectClass=posixGroup)', search_scope='BASE', attributes=['memberUid']):
                group_entry = conn.entries[0]
                member_uids = group_entry.memberUid.values if 'memberUid' in group_entry else []
                if user['uid'] not in member_uids:
                    if conn.modify(group_dn, {'memberUid': [(MODIFY_ADD, [user['uid']])]}):
                        print(f"User {user['uid']} added to posix group {group_name}.")
                    else:
                        print(f"Failed to add user {user['uid']} to posix group {group_name}: {conn.result['description']}")
                else:
                    print(f"User {user['uid']} is already a member of posix group {group_name}.")
            else:
                print(f"Failed to search posix group {group_name}: {conn.result['description']}")

def handle_group_of_names_memberships(conn, user_dn, user, group_base):
    """
    Handles groupOfNames memberships for the user.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        user_dn (str): The distinguished name of the user.
        user (dict): User details.
        group_base (str): The group base DN.

    Returns:
        None
    """
    user_groups = user.get('groups', [])
    for group_name in user_groups:
        group_dn = f"cn={group_name},{group_base}"
        if not conn.search(group_dn, '(objectClass=groupOfNames)', search_scope='BASE', attributes=['member']):
            group_attrs = {
                'objectClass': ['groupOfNames', 'top'],
                'cn': group_name,
                'member': [user_dn]
            }
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


def create_ldap_user(user, ldap_config):
    """
    Main function to create or update an LDAP user and manage group memberships.

    Args:
        user (dict): User details.
        ldap_config (dict): LDAP configuration details.

    Returns:
        None
    """
    conn = None
    try:
        conn = connect_to_ldap(ldap_config)
        group_base = ldap_config.get('group_base', 'ou=groups,dc=example,dc=org')

        if not ensure_group_base_dn_exists(conn, group_base):
            print(f"Cannot proceed without group base DN: {group_base}")
            return

        user_dn = f"uid={user['uid']},{ldap_config['user_base']}"
        attrs = prepare_user_attributes(user)
        create_or_update_user(conn, user_dn, attrs)

        # Build group_gid_map from existing posixGroups
        group_gid_map = get_existing_posix_groups(conn, group_base)
        handle_posix_group_memberships(conn, user, group_base, group_gid_map)
        handle_group_of_names_memberships(conn, user_dn, user, group_base)

    except LDAPException as e:
        print(f"Error in creating user {user['uid']}: {e}")
        traceback.print_exc()
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
