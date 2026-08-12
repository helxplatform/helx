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
        ldap_config (dict): LDAP configuration containing at least
            'ldap_server', 'bind_dn', and 'bind_password'.

    Returns:
        ldap3.Connection: A bound LDAP connection.
    """
    server_url = ldap_config.get("ldap_server")
    if not server_url:
        raise ValueError("ldap_server must be specified in the config or via command-line.")
    
    parsed = urlparse(server_url)
    host = parsed.hostname
    port = parsed.port or (636 if parsed.scheme == "ldaps" else 389)
    use_ssl = (parsed.scheme == "ldaps")

    server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)
    conn = Connection(
        server,
        user=ldap_config.get("bind_dn"),
        password=ldap_config.get("bind_password"),
        auto_bind=True
    )
    return conn

def retrieve_posix_group(conn, group_name, group_base):
    """
    Retrieve a specific posixGroup entry given its common name.
    """
    dn = f"cn={group_name},{group_base}"
    if conn.search(search_base=dn,
                   search_filter="(objectClass=posixGroup)",
                   search_scope='BASE',
                   attributes=['*']):
        return conn.entries[0]
    return None

def retrieve_all_posix_groups_full(conn, group_base):
    """
    Retrieve all posixGroup entries under the specified group base with full details.
    """
    if conn.search(search_base=group_base,
                   search_filter="(objectClass=posixGroup)",
                   search_scope='SUBTREE',
                   attributes=['*']):
        return [e.entry_attributes_as_dict for e in conn.entries]
    return []

def retrieve_users_with_gid(conn, gid, user_base):
    """
    Find all users under user_base whose gidNumber matches gid,
    returning their uid attributes as a list of usernames.
    """
    filter_ = f"(gidNumber={gid})"
    if conn.search(search_base=user_base,
                   search_filter=filter_,
                   search_scope='SUBTREE',
                   attributes=['uid']):
        return [e.uid.value for e in conn.entries if hasattr(e, 'uid')]
    return []

class CustomIndent(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        # Force indentation of sequences within mappings.
        return super(CustomIndent, self).increase_indent(flow, False)

def transform_group_dict(group_dict):
    """
    Transform the LDAP group entry dictionary:
      - 'cn' → 'name' (scalar)
      - 'gidNumber' → scalar
      - 'memberUid' → 'members' (list)
      - other keys unchanged
    Ensures 'members' exists (even as empty list).
    """
    out = {}
    for k, v in group_dict.items():
        if k == "cn":
            out["name"] = v[0] if isinstance(v, list) and v else v
        elif k == "gidNumber":
            out["gidNumber"] = v[0] if isinstance(v, list) and v else v
        elif k == "memberUid":
            out["members"] = v if isinstance(v, list) else [v]
        else:
            out[k] = v
    if "members" not in out:
        out["members"] = []
    return out

def main():
    p = argparse.ArgumentParser(
        description="Retrieve posixGroup(s) from LDAP and print their contents as YAML."
    )
    p.add_argument("--group-name",
                   help="cn of the posixGroup to retrieve")
    p.add_argument("--ldap-server",
                   help="LDAP server URL (overrides config)", default=None)
    p.add_argument("--bind-dn",
                   help="Bind DN (overrides config)", default=None)
    p.add_argument("--bind-password",
                   help="Bind password (overrides config)", default=None)
    p.add_argument("--group-base",
                   help="Base DN for groups (overrides config)",
                   default=None)
    p.add_argument("--user-base",
                   help="Base DN for users (overrides config)",
                   default=None)
    p.add_argument("--fix-members", action="store_true",
                   help="Replace members with all users whose gidNumber matches")
    p.add_argument("--config",
                   help="Path to YAML config file", default="helx_ldap_config.yaml")
    args = p.parse_args()

    cfg_file = load_ldap_config(args.config)
    ldap_cfg = {
        "ldap_server": args.ldap_server or cfg_file.get("ldap", {}).get("server_url"),
        "bind_dn":      args.bind_dn      or cfg_file.get("ldap", {}).get("admin", {}).get("bind_dn"),
        "bind_password":args.bind_password or cfg_file.get("ldap", {}).get("admin", {}).get("password"),
        "group_base":   args.group_base   or cfg_file.get("ldap", {}).get("group_base", "ou=groups,dc=example,dc=org"),
        "user_base":    args.user_base    or cfg_file.get("ldap", {}).get("user_base",  "ou=users,dc=example,dc=org")
    }

    if not ldap_cfg["ldap_server"] or not ldap_cfg["bind_password"]:
        print("Error: must provide ldap_server and bind_password (via args or config)")
        return

    try:
        conn = connect_to_ldap(ldap_cfg)

        def process_raw(raw):
            g = transform_group_dict(raw)
            if args.fix_members:
                # override members
                g["members"] = retrieve_users_with_gid(
                    conn, g["gidNumber"], ldap_cfg["user_base"]
                )
            return g

        if args.group_name:
            ent = retrieve_posix_group(conn, args.group_name, ldap_cfg["group_base"])
            if ent:
                processed = process_raw(ent.entry_attributes_as_dict)
                print(yaml.dump(processed,
                                Dumper=CustomIndent,
                                default_flow_style=False,
                                indent=2))
            else:
                print(f"Group '{args.group_name}' not found under {ldap_cfg['group_base']}")
        else:
            raws = retrieve_all_posix_groups_full(conn, ldap_cfg["group_base"])
            processed_all = [process_raw(r) for r in raws]
            print(yaml.dump({"posixGroups": processed_all},
                            Dumper=CustomIndent,
                            default_flow_style=False,
                            indent=2))

    except Exception as e:
        print("An error occurred:", e)
    finally:
        if 'conn' in locals():
            conn.unbind()

if __name__ == "__main__":
    main()
