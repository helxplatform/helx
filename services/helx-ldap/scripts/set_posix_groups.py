#!/usr/bin/env python

import sys
import os
import yaml
import argparse
from urllib.parse import urlparse
from ldap3 import Server, Connection, ALL, MODIFY_ADD, MODIFY_DELETE, MODIFY_REPLACE

def load_ldap_config(config_file="helx_ldap_config.yaml"):
    if os.path.exists(config_file):
        with open(config_file) as f:
            return yaml.safe_load(f)
    return {}

def connect_to_ldap(ldap_cfg):
    url = ldap_cfg["ldap_server"]
    if not url:
        raise ValueError("ldap_server must be set (via --ldap-server or config)")
    p = urlparse(url)
    host = p.hostname
    port = p.port or (636 if p.scheme == "ldaps" else 389)
    use_ssl = (p.scheme == "ldaps")
    server = Server(host, port=port, use_ssl=use_ssl, get_info=ALL)
    return Connection(
        server,
        user=ldap_cfg["bind_dn"],
        password=ldap_cfg["bind_password"],
        auto_bind=True
    )

def retrieve_posix_group_raw(conn, cn, base_dn):
    dn = f"cn={cn},{base_dn}"
    if conn.search(dn, "(objectClass=posixGroup)",
                   search_scope='BASE', attributes=['*']):
        return conn.entries[0].entry_attributes_as_dict
    return None

def apply_changes(conn, group, ldap_cfg):
    """
    Apply the desired 'members' and 'gidNumber' from the YAML group dict
    back into LDAP.
    """
    name     = group["name"]
    gid      = str(group["gidNumber"])
    desired  = group.get("members", [])
    base_dn  = ldap_cfg["group_base"]
    dn       = f"cn={name},{base_dn}"

    current = retrieve_posix_group_raw(conn, name, base_dn)
    if current is None:
        print(f"[ERROR] group '{name}' not found under {base_dn}", file=sys.stderr)
        return

    current_members = current.get("memberUid", [])
    to_add    = sorted(set(desired) - set(current_members))
    to_remove = sorted(set(current_members) - set(desired))

    # Check gidNumber change
    orig_gid = current.get("gidNumber", [])
    orig_gid = orig_gid[0] if isinstance(orig_gid, list) and orig_gid else orig_gid
    gid_mods = []
    if gid != str(orig_gid):
        gid_mods = [(MODIFY_REPLACE, [gid])]

    mods = {}
    if to_add:
        mods.setdefault('memberUid', []).append((MODIFY_ADD, to_add))
    if to_remove:
        mods.setdefault('memberUid', []).append((MODIFY_DELETE, to_remove))
    if gid_mods:
        mods['gidNumber'] = gid_mods

    if not mods:
        print(f"[OK] {name}: no changes needed")
        return

    success = conn.modify(dn, mods)
    if not success:
        print(f"[ERROR] modifying '{name}': {conn.result['description']}", file=sys.stderr)
    else:
        actions = []
        if to_add:    actions.append(f"added members {to_add}")
        if to_remove: actions.append(f"removed members {to_remove}")
        if gid_mods:  actions.append(f"set gidNumber to {gid}")
        print(f"[OK] {name}: " + ", ".join(actions))

def main():
    p = argparse.ArgumentParser(
        description="Apply posixGroup changes from a YAML file back into LDAP."
    )
    p.add_argument("input_file",
                   help="YAML file with 'posixGroups' list or a single group dict")
    p.add_argument("--ldap-server",   help="LDAP URL (overrides config)", default=None)
    p.add_argument("--bind-dn",       help="Bind DN (overrides config)",    default=None)
    p.add_argument("--bind-password", help="Bind password (overrides config)", default=None)
    p.add_argument("--group-base",    help="Base DN for groups (overrides config)",
                   default=None)
    p.add_argument("--config",        help="Path to YAML config file",       default="helx_ldap_config.yaml")
    args = p.parse_args()

    cfg = load_ldap_config(args.config).get("ldap", {})
    ldap_cfg = {
        "ldap_server":   args.ldap_server   or cfg.get("server_url"),
        "bind_dn":       args.bind_dn       or cfg.get("admin", {}).get("bind_dn"),
        "bind_password": args.bind_password or cfg.get("admin", {}).get("password"),
        "group_base":    args.group_base    or cfg.get("group_base", "ou=groups,dc=example,dc=org")
    }

    if not ldap_cfg["ldap_server"] or not ldap_cfg["bind_password"]:
        print("Error: ldap_server & bind_password are required", file=sys.stderr)
        sys.exit(1)

    # Load the YAML file
    try:
        with open(args.input_file) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading '{args.input_file}': {e}", file=sys.stderr)
        sys.exit(1)

    # Determine list of group dicts
    groups = data.get("posixGroups") if isinstance(data, dict) and "posixGroups" in data else [data]

    # Connect and apply
    conn = connect_to_ldap(ldap_cfg)
    try:
        for grp in groups:
            apply_changes(conn, grp, ldap_cfg)
    finally:
        conn.unbind()

if __name__ == "__main__":
    main()
