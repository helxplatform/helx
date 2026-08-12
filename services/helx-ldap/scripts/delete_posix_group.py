#!/usr/bin/env python

import sys
import os
import yaml
import argparse
from urllib.parse import urlparse
from ldap3 import Server, Connection, ALL, SUBTREE

def load_ldap_config(config_file="helx_ldap_config.yaml"):
    if os.path.exists(config_file):
        with open(config_file) as f:
            return yaml.safe_load(f)
    return {}

def connect_to_ldap(ldap_cfg):
    url = ldap_cfg["ldap_server"]
    if not url:
        raise ValueError("ldap_server must be set via --ldap-server or config file")
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

def find_groups_by_gid(conn, gid, group_base):
    """Return list of LDAP entries for posixGroup objects with gidNumber=gid."""
    flt = f"(gidNumber={gid})"
    if conn.search(search_base=group_base,
                   search_filter=flt,
                   search_scope=SUBTREE,
                   attributes=['cn']):
        return conn.entries
    return []

def find_users_by_gid(conn, gid, user_base):
    """Return list of uid strings for users with gidNumber=gid."""
    flt = f"(gidNumber={gid})"
    if conn.search(search_base=user_base,
                   search_filter=flt,
                   search_scope=SUBTREE,
                   attributes=['uid']):
        return [e.uid.value for e in conn.entries if hasattr(e, 'uid')]
    return []

def delete_group(conn, dn, name):
    """Delete the entry at dn; report success or error."""
    if conn.delete(dn):
        print(f"[OK] Deleted group '{name}' ({dn})")
    else:
        print(f"[ERROR] Failed to delete '{name}' ({dn}): {conn.result['description']}", file=sys.stderr)

def main():
    p = argparse.ArgumentParser(
        description="Delete a posixGroup by gidNumber, aborting if users reference it (unless --force)."
    )
    p.add_argument("gid_number", type=int,
                   help="GID number of the posixGroup to delete")
    p.add_argument("--force", action="store_true",
                   help="Delete the group even if users have that gidNumber")
    p.add_argument("--ldap-server",   help="LDAP URL (overrides config)", default=None)
    p.add_argument("--bind-dn",       help="Bind DN (overrides config)",    default=None)
    p.add_argument("--bind-password", help="Bind password (overrides config)", default=None)
    p.add_argument("--group-base",    help="Base DN for groups (overrides config)", default=None)
    p.add_argument("--user-base",     help="Base DN for users (overrides config)",  default=None)
    p.add_argument("--config",        help="Path to YAML config file",             default="helx_ldap_config.yaml")
    args = p.parse_args()

    cfg = load_ldap_config(args.config).get("ldap", {})
    ldap_cfg = {
        "ldap_server":   args.ldap_server   or cfg.get("server_url"),
        "bind_dn":       args.bind_dn       or cfg.get("admin", {}).get("bind_dn"),
        "bind_password": args.bind_password or cfg.get("admin", {}).get("password"),
        "group_base":    args.group_base    or cfg.get("group_base", "ou=groups,dc=example,dc=org"),
        "user_base":     args.user_base     or cfg.get("user_base",  "ou=users,dc=example,dc=org")
    }

    if not ldap_cfg["ldap_server"] or not ldap_cfg["bind_dn"] or not ldap_cfg["bind_password"]:
        print("Error: ldap_server, bind_dn, and bind_password are required", file=sys.stderr)
        sys.exit(1)

    try:
        conn = connect_to_ldap(ldap_cfg)

        groups = find_groups_by_gid(conn, args.gid_number, ldap_cfg["group_base"])
        if not groups:
            print(f"[ERROR] No posixGroup with gidNumber={args.gid_number} found under {ldap_cfg['group_base']}", file=sys.stderr)
            sys.exit(1)

        users = find_users_by_gid(conn, args.gid_number, ldap_cfg["user_base"])
        if users and not args.force:
            print(f"[ERROR] Users exist with gidNumber={args.gid_number}: {users}. Use --force to delete anyway.", file=sys.stderr)
            sys.exit(1)

        for entry in groups:
            dn   = entry.entry_dn
            name = entry.cn.value if hasattr(entry, 'cn') else dn
            delete_group(conn, dn, name)

    except Exception as e:
        print(f"[ERROR] Exception: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if 'conn' in locals():
            conn.unbind()

if __name__ == "__main__":
    main()
