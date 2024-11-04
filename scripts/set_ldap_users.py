#!/usr/bin/env python

from ldap3 import Server, Connection, ALL, MODIFY_ADD, MODIFY_REPLACE, MODIFY_DELETE, SUBTREE
from ldap3.core.exceptions import LDAPException
import yaml
import argparse
from urllib.parse import urlparse
import os
import traceback

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
    Ensures that the group base DN exists in the LDAP directory by checking and creating 
    each parent DN as necessary, starting from the root.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_base (str): The full group base DN (e.g., ou=groups,dc=example,dc=org).

    Returns:
        bool: True if the group base DN exists or was created successfully.
    """

    dn_components = group_base.split(',')
    
    # Work through the DN components from root (rightmost) to leaf (leftmost)
    for i in range(len(dn_components)):
        # Build the full DN progressively from root to leaf
        dn = ','.join(dn_components[len(dn_components)-1-i:])
        
        # Check if the full DN exists
        if not conn.search(dn, '(objectClass=*)', search_scope='BASE'):
            # Create 'ou' components as organizational units
            if dn_components[len(dn_components)-1-i].startswith("ou="):
                ou_name = dn_components[len(dn_components)-1-i][3:]  # Extract the 'ou' part (e.g., 'groups')
                attrs = {
                    'objectClass': ['top', 'organizationalUnit'],
                    'ou': ou_name
                }
                print(f"Creating {dn}...")
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

    # Ensure either 'runAsUser' or 'uidNumber' are present
    if 'runAsUser' not in user and 'uidNumber' not in user:
        raise ValueError(f"'either runAsUser' or 'uidNumber' must be provided for user {user['uid']}")
    
    # Ensure either 'runAsGroup' or 'gidNumber' are present
    if 'runAsGroup' not in user and 'gidNumber' not in user:
        raise ValueError(f"'either runAsGroup' or 'gidNumber' must be provided for user {user['uid']}")

    # Set 'uidNumber' and 'gidNumber' if not present
    if not user.get('uidNumber',None): user['uidNumber'] = user['runAsUser']
    if not user.get('gidNumber',None): user['gidNumber'] = user['runAsGroup']

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
        'uid': user.get('uid', None),
        'cn': user.get('cn', None),
        'sn': user.get('sn', None),
        'mail': user.get('email', None),
        'telephoneNumber': user.get('telephoneNumber', None),
        'o': user.get('o', None),
        'ou': user.get('ou', None),
        'givenName': user.get('givenName', None),
        'displayName': user.get('displayName', None),
        'supplementalGroups': [str(group) for group in user.get('supplementalGroups', [])] if 'supplementalGroups' in user else None,
        'runAsUser': str(user.get('runAsUser', None)) if 'runAsUser' in user else None,
        'runAsGroup': str(user.get('runAsGroup', None)) if 'runAsGroup' in user else None,
        'fsGroup': str(user.get('fsGroup', None)) if 'fsGroup' in user else None,
        'uidNumber': str(user.get('uidNumber', None)) if 'uidNumber' in user else None,
        'gidNumber': str(user.get('gidNumber', None)) if 'gidNumber' in user else None,
        'homeDirectory': user.get('homeDirectory', None),
        'loginShell': user.get('loginShell', None)
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

    if 'supplementalGroups' in attrs:
        if not attrs['supplementalGroups']:
            attrs['supplementalGroups'] = None
        else:
            valid_groups = []
            for val in attrs['supplementalGroups']:
                try:
                    int_val = int(val)
                    valid_groups.append(int_val)
                except ValueError:
                    # Handle the case where the value cannot be converted to an integer
                    print(f"Invalid supplementalGroup value: {val}")
                    pass  # You can choose to skip invalid values or handle them differently
            if valid_groups:
                attrs['supplementalGroups'] = valid_groups
            else:
                attrs['supplementalGroups'] = None

    if conn.search(user_dn, '(objectClass=*)', search_scope='BASE', attributes=['*']):
        existing_entry = conn.entries[0]
        existing_attrs = existing_entry.entry_attributes_as_dict
        modifications = {}

        # Compare and update attributes
        for attr, new_value in attrs.items():
            existing_value = existing_attrs.get(attr, [])
            
            if new_value is None:
                # If new value is None, mark the attribute for deletion if it exists in LDAP
                if existing_value:
                    print("deleting ",attr)
                    modifications[attr] = [(MODIFY_DELETE, [])]
            else:
                if isinstance(new_value, list):
                    # Check if the new list is different from the existing list
                    if set(new_value) != set(existing_value):
                        modifications[attr] = [(MODIFY_REPLACE, new_value)]
                else:
                    # Check if the new single value is different from the existing one
                    if new_value != (existing_value[0] if existing_value else ''):
                        modifications[attr] = [(MODIFY_REPLACE, [new_value])]

        # If there are modifications, apply them
        if modifications:
            if conn.modify(user_dn, modifications):
                print(f"User {attrs['uid']} updated successfully.")
            else:
                print(f"Failed to update user {attrs['uid']}: {conn.result['description']}")
        else:
            print(f"No updates necessary for user {attrs['uid']}.")
    else:
        # Filter out None values for user creation (we don't want to create entries with None attributes)
        cleaned_attrs = {k: v for k, v in attrs.items() if v is not None}

        # If the user doesn't exist, create them
        if conn.add(user_dn, attributes=cleaned_attrs):
            print(f"User {attrs['uid']} created successfully.")
        else:
            print(f"Failed to create user {attrs['uid']}: {conn.result['description']}")

def get_existing_posix_groups(conn, group_base):
    """
    Retrieves existing posixGroup entries from LDAP, along with their gidNumbers and memberUids.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_base (str): The group base DN.

    Returns:
        dict: A mapping of group names to a tuple (gidNumber, memberUids).
    """
    group_info_map = {}
    conn.search(
        search_base=group_base,
        search_filter='(objectClass=posixGroup)',
        search_scope=SUBTREE,
        attributes=['cn', 'gidNumber', 'memberUid']
    )
    
    for entry in conn.entries:
        group_name = entry.cn.value
        gid_number = int(entry.gidNumber.value)
        member_uids = entry.memberUid.values if 'memberUid' in entry else []
        group_info_map[group_name] = (gid_number, member_uids)
    
    return group_info_map


def handle_posix_group_memberships(conn, user, group_base, group_info_map):
    """
    Handles posixGroup memberships for the user by adding the user to new groups
    and removing the user from groups they are no longer a member of.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        user (dict): User details.
        group_base (str): The group base DN.
        group_info_map (dict): A mapping of group names to tuples (gidNumber, memberUids).

    Returns:
        None
    """
    # Get the new posixGroups memberships from the user dictionary
    posix_groups = user.get('posixGroups', None)
    if posix_groups is None: posix_groups = []

    # Get the user's current posixGroup memberships from the group_info_map
    current_posix_groups = [group_name for group_name, (_, members) in group_info_map.items() if user['uid'] in members]

    # Determine which groups to add the user to
    groups_to_add = set(posix_groups) - set(current_posix_groups)

    # Determine which groups to remove the user from
    groups_to_remove = set(current_posix_groups) - set(posix_groups)

    # Add the user to new posix groups
    for group_name in groups_to_add:
        group_dn = f"cn={group_name},{group_base}"

        # Check if the group exists
        if group_name in group_info_map:
            gid_number, _ = group_info_map[group_name]
            group_exists = True
        else:
            # If the group does not exist, assign a new gidNumber
            gid_number = max(group_info_map.values(), default=(8192, []))[0] + 1
            group_info_map[group_name] = (gid_number, [])
            group_exists = False

        if not group_exists:
            # Create the posixGroup
            group_attrs = {
                'objectClass': ['posixGroup', 'top'],
                'cn': group_name,
                'gidNumber': str(gid_number),
                'memberUid': [user['uid']]
            }
            if conn.add(f"cn={group_name},{group_base}", attributes=group_attrs):
                print(f"Posix group {group_name} created with gidNumber {gid_number} and user {user['uid']} added as member.")
            else:
                print(f"Failed to create posix group {group_name}: {conn.result['description']}")
        else:
            # Group exists, add the user to the group
            if conn.modify(group_dn, {'memberUid': [(MODIFY_ADD, [user['uid']])]}):
                print(f"User {user['uid']} added to posix group {group_name}.")
            else:
                print(f"Failed to add user {user['uid']} to posix group {group_name}: {conn.result['description']}")

    # Remove the user from old posix groups
    for group_name in groups_to_remove:
        group_dn = f"cn={group_name},{group_base}"
        if conn.modify(group_dn, {'memberUid': [(MODIFY_DELETE, [user['uid']])]}):
            print(f"User {user['uid']} removed from posix group {group_name}.")
        else:
            print(f"Failed to remove user {user['uid']} from posix group {group_name}: {conn.result['description']}")


def handle_group_of_names_memberships(conn, user_dn, user, group_base):
    """
    Handles groupOfNames memberships for the user by adding the user to new groups
    and removing the user from groups they are no longer a member of.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        user_dn (str): The distinguished name of the user.
        user (dict): User details.
        group_base (str): The group base DN.

    Returns:
        None
    """
    # Get the new group memberships from the user dictionary
    user_groups = user.get('groups', None)
    if user_groups is None: user_groups = []
    
    # Search for all groups that currently contain this user
    current_groups = []
    conn.search(group_base, f'(member={user_dn})', search_scope='SUBTREE', attributes=['cn'])
    for entry in conn.entries:
        current_groups.append(str(entry.cn))
    
    # Determine groups to add the user to (in new list but not in current)
    groups_to_add = set(user_groups) - set(current_groups)
    
    # Determine groups to remove the user from (in current list but not in new list)
    groups_to_remove = set(current_groups) - set(user_groups)
    
    # Add the user to new groups
    for group_name in groups_to_add:
        group_dn = f"cn={group_name},{group_base}"
        if not conn.search(group_dn, '(objectClass=groupOfNames)', search_scope='BASE', attributes=['member']):
            # Group doesn't exist, so create it and add the user as the first member
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
            # Group exists, just add the user
            if conn.modify(group_dn, {'member': [(MODIFY_ADD, [user_dn])]}):
                print(f"User {user['uid']} added to group {group_name}.")
            else:
                print(f"Failed to add user {user['uid']} to group {group_name}: {conn.result['description']}")
    
    # Remove the user from groups they are no longer a part of
    for group_name in groups_to_remove:
        group_dn = f"cn={group_name},{group_base}"
        if conn.modify(group_dn, {'member': [(MODIFY_DELETE, [user_dn])]}):
            print(f"User {user['uid']} removed from group {group_name}.")
        else:
            print(f"Failed to remove user {user['uid']} from group {group_name}: {conn.result['description']}")


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
