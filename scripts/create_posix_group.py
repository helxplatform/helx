#!/usr/bin/env python

import os
import yaml
import argparse
from urllib.parse import urlparse
from ldap3 import Server, Connection, ALL

def load_ldap_config(config_file="helx_ldap_config.yaml"):
    """
    Load LDAP configuration from a YAML file.

    Args:
        config_file (str): Path to the YAML configuration file.

    Returns:
        dict: LDAP configuration dictionary (or an empty dict if file is not found).
    """
    if os.path.exists(config_file):
        with open(config_file, "r") as file:
            return yaml.safe_load(file)
    return {}

def connect_to_ldap(ldap_config):
    """
    Connect to the LDAP server using parameters from the configuration.

    Args:
        ldap_config (dict): LDAP configuration containing at least 'ldap_server', 'bind_dn', and 'bind_password'.

    Returns:
        ldap3.Connection: A bound LDAP connection.
    """
    server_url = ldap_config.get("ldap_server")
    if not server_url:
        raise ValueError("ldap_server must be specified in the config or via command-line.")
    
    parsed_url = urlparse(server_url)
    host = parsed_url.hostname
    port = parsed_url.port or (636 if parsed_url.scheme == "ldaps" else 389)
    use_ssl = parsed_url.scheme == "ldaps"

    server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)
    conn = Connection(server,
                      user=ldap_config.get("bind_dn"),
                      password=ldap_config.get("bind_password"),
                      auto_bind=True)
    return conn

def ensure_group_base_exists(conn, group_base):
    """
    Ensure that each component of the group_base DN exists in LDAP.
    If a DN segment starting with 'ou=' is missing, it will be created.
    
    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_base (str): The group base DN (e.g. "ou=groups,dc=example,dc=org").
    
    Returns:
        bool: True if the group base (and any missing parents) exists or was created.
    """
    dn_components = group_base.split(',')
    # Work from the root upward: build each DN segment (from right to left)
    for i in range(len(dn_components)):
        current_dn = ','.join(dn_components[i:])
        if not conn.search(current_dn, '(objectClass=*)', search_scope='BASE'):
            # Only create entries that are organizational units (ou=...)
            if current_dn.startswith("ou="):
                ou_value = current_dn.split('=')[1].split(',')[0]
                attrs = {
                    "objectClass": ["top", "organizationalUnit"],
                    "ou": ou_value
                }
                print(f"Creating missing DN: {current_dn}")
                if not conn.add(current_dn, attributes=attrs):
                    print(f"Failed to create {current_dn}: {conn.result['description']}")
                    return False
    return True

def create_posix_group(conn, group_name, gid_number, group_base):
    """
    Create a posixGroup entry in the LDAP directory.

    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_name (str): The common name (cn) of the group.
        gid_number (int): The gidNumber for the group.
        group_base (str): The base DN where the group will be created.
    """
    group_dn = f"cn={group_name},{group_base}"
    
    # Check if the group already exists.
    if conn.search(group_dn, '(objectClass=posixGroup)', search_scope='BASE'):
        print(f"Group '{group_name}' already exists under {group_base}.")
        return

    attrs = {
        "objectClass": ["posixGroup", "top"],
        "cn": group_name,
        "gidNumber": str(gid_number)
    }
    
    if conn.add(group_dn, attributes=attrs):
        print(f"Posix group '{group_name}' created successfully with gidNumber {gid_number} at DN: {group_dn}")
    else:
        print(f"Failed to create posix group '{group_name}': {conn.result['description']}")

def main():
    parser = argparse.ArgumentParser(
        description="Create a single posixGroup in LDAP with a supplied group name and gidNumber. "
                    "Connection parameters are read from helx_ldap_config.yaml by default."
    )
    parser.add_argument("group_name", help="Name (cn) of the group to create")
    parser.add_argument("gid_number", help="gidNumber for the group", type=int)
    parser.add_argument("--ldap-server", help="LDAP server URL (overrides config file)", default=None)
    parser.add_argument("--bind-dn", help="LDAP Bind DN (overrides config file)", default=None)
    parser.add_argument("--bind-password", help="LDAP Bind password (overrides config file)", default=None)
    parser.add_argument("--group-base", help="Base DN for groups (overrides config file)", default=None)
    parser.add_argument("--config", help="Path to the YAML config file", default="helx_ldap_config.yaml")
    
    args = parser.parse_args()
    
    # Load the configuration from file
    config = load_ldap_config(args.config)
    
    # Merge command-line arguments over config file values (if provided)
    ldap_config = {
        "ldap_server": args.ldap_server or config.get("ldap", {}).get("server_url"),
        "bind_dn": args.bind_dn or config.get("ldap", {}).get("admin", {}).get("bind_dn"),
        "bind_password": args.bind_password or config.get("ldap", {}).get("admin", {}).get("password"),
        "group_base": args.group_base or config.get("ldap", {}).get("group_base", "ou=groups,dc=example,dc=org")
    }
    
    if not ldap_config["ldap_server"] or not ldap_config["bind_password"]:
        print("Error: Both LDAP server URL and bind password must be provided via command-line or config file.")
        return
    
    try:
        conn = connect_to_ldap(ldap_config)
        if not ensure_group_base_exists(conn, ldap_config["group_base"]):
            print("Error: Could not ensure the group base DN exists.")
            return
        create_posix_group(conn, args.group_name, args.gid_number, ldap_config["group_base"])
    except Exception as e:
        print("An error occurred:", e)
    finally:
        if 'conn' in locals() and conn:
            conn.unbind()

if __name__ == "__main__":
    main()
