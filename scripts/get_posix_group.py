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

def retrieve_posix_group(conn, group_name, group_base):
    """
    Retrieve a specific posixGroup entry given its common name.
    
    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_name (str): The common name (cn) of the group to retrieve.
        group_base (str): The base DN for groups.
    
    Returns:
        The LDAP entry for the group if found, or None.
    """
    group_dn = f"cn={group_name},{group_base}"
    if conn.search(
            search_base=group_dn,
            search_filter="(objectClass=posixGroup)",
            search_scope='BASE',
            attributes=['*']):
        return conn.entries[0]
    return None

def retrieve_all_posix_groups_full(conn, group_base):
    """
    Retrieve all posixGroup entries under the specified group base with full details.
    
    Args:
        conn (ldap3.Connection): An active LDAP connection.
        group_base (str): The base DN where posixGroup entries reside.
    
    Returns:
        list: A list of dictionaries, where each dictionary contains all attributes for a posixGroup.
    """
    if conn.search(
            search_base=group_base,
            search_filter="(objectClass=posixGroup)",
            search_scope='SUBTREE',
            attributes=['*']):
        return [entry.entry_attributes_as_dict for entry in conn.entries]
    return []

class CustomIndent(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        # Force indentation of sequences within mappings.
        return super(CustomIndent, self).increase_indent(flow, False)

def transform_group_dict(group_dict):
    """
    Transform the LDAP group entry dictionary.
      - Rename 'cn' to 'name' and flatten its list value to a single string.
      - Flatten 'gidNumber' list into a single value.
      
    Args:
        group_dict (dict): Original group attributes.
    
    Returns:
        dict: Transformed group dictionary.
    """
    transformed = {}
    for key, value in group_dict.items():
        if key == "cn":
            transformed["name"] = value[0] if isinstance(value, list) and value else value
        elif key == "gidNumber":
            transformed["gidNumber"] = value[0] if isinstance(value, list) and value else value
        else:
            transformed[key] = value
    return transformed

def main():
    parser = argparse.ArgumentParser(
        description="Retrieve posixGroup(s) from LDAP and print their contents as YAML. "
                    "If --group-name is specified, retrieves and prints that group's full details; "
                    "otherwise, prints the full details of all posixGroups."
    )
    parser.add_argument("--group-name", help="Common name (cn) of the posixGroup to retrieve")
    parser.add_argument("--ldap-server", help="LDAP server URL (overrides config file)", default=None)
    parser.add_argument("--bind-dn", help="LDAP Bind DN (overrides config file)", default=None)
    parser.add_argument("--bind-password", help="LDAP Bind password (overrides config file)", default=None)
    parser.add_argument("--group-base", help="Base DN for groups (overrides config file)", default=None)
    parser.add_argument("--config", help="Path to the YAML config file", default="helx_ldap_config.yaml")
    
    args = parser.parse_args()
    
    # Load configuration from the YAML file.
    config = load_ldap_config(args.config)
    
    # Merge command-line options over configuration file values.
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
        
        if args.group_name:
            group_entry = retrieve_posix_group(conn, args.group_name, ldap_config["group_base"])
            if group_entry:
                group_dict = group_entry.entry_attributes_as_dict
                transformed = transform_group_dict(group_dict)
                print(yaml.dump(transformed, Dumper=CustomIndent, default_flow_style=False, indent=2))
            else:
                print(f"posixGroup with name '{args.group_name}' not found under base '{ldap_config['group_base']}'.")
        else:
            groups = retrieve_all_posix_groups_full(conn, ldap_config["group_base"])
            transformed_groups = [transform_group_dict(g) for g in groups]
            print(yaml.dump({"posixGroups": transformed_groups}, Dumper=CustomIndent, default_flow_style=False, indent=2))
    except Exception as e:
        print("An error occurred:", e)
    finally:
        if 'conn' in locals() and conn:
            conn.unbind()

if __name__ == "__main__":
    main()
