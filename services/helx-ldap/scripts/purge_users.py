#!/usr/bin/env python
"""
purge_users.py

This script connects to an LDAP server using configuration from helx_ldap_config.yaml.
It takes a single command-line argument <groupname>, derives the base DN from the admin bind_dn,
and then finds all user entries (objectClass 'person') under that base DN.
Users whose 'memberOf' attribute does not include the specified group (found as a groupOfNames with matching cn)
are listed and, after confirmation (default N), are deleted.
"""

import ldap
import ldap.filter
import argparse
import sys
import yaml

def load_config(config_file="helx_ldap_config.yaml"):
    try:
        with open(config_file, "r") as f:
            config = yaml.load(f, Loader=yaml.FullLoader)
        return config
    except Exception as e:
        print(f"Error loading configuration file {config_file}: {e}")
        sys.exit(1)

def get_base_dn(config):
    """
    Derive the base DN from the admin bind_dn.
    For example, if bind_dn is 'cn=admin,dc=example,dc=org', then base DN will be 'dc=example,dc=org'.
    """
    try:
        bind_dn = config["ldap"]["admin"]["bind_dn"]
        parts = bind_dn.split(",", 1)
        if len(parts) < 2:
            raise ValueError("Invalid admin bind_dn format; cannot derive base DN.")
        base_dn = parts[1].strip()
        return base_dn
    except Exception as e:
        print("Error deriving base DN:", e)
        sys.exit(1)

def get_ldap_connection(config):
    try:
        server_url = config["ldap"]["server_url"]
        bind_dn = config["ldap"]["admin"]["bind_dn"]
        bind_pw = config["ldap"]["admin"]["password"]
    except KeyError as e:
        print("Missing LDAP configuration key:", e)
        sys.exit(1)
    
    try:
        conn = ldap.initialize(server_url)
        conn.protocol_version = ldap.VERSION3
        conn.simple_bind_s(bind_dn, bind_pw)
        return conn
    except ldap.LDAPError as e:
        print("LDAP connection error:", e)
        sys.exit(1)

def get_group_dn(conn, base_dn, groupname):
    """
    Retrieve the DN of the group identified by the provided groupname.
    Assumes that groups are stored as objectClass 'groupOfNames' and that the 'cn' attribute equals the groupname.
    """
    filter_str = f"(&(objectClass=groupOfNames)(cn={ldap.filter.escape_filter_chars(groupname)}))"
    try:
        results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, filter_str, ['dn'])
        if not results:
            print(f"Group '{groupname}' not found.")
            sys.exit(1)
        group_dn = results[0][0]
        return group_dn
    except ldap.LDAPError as e:
        print("Error searching for group:", e)
        sys.exit(1)

def find_users_to_purge(conn, base_dn, group_dn):
    """
    Search for all users (objectClass 'person') under the base DN.
    Returns a list of user DNs whose 'memberOf' attribute does not include the given group_dn.
    """
    filter_str = "(objectClass=person)"
    try:
        results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, filter_str, ['dn', 'memberOf'])
    except ldap.LDAPError as e:
        print("Error searching for users:", e)
        sys.exit(1)
    
    users_to_purge = []
    for dn, attrs in results:
        memberOf = attrs.get('memberOf', [])
        # Convert memberOf values from bytes to strings if necessary
        memberOf = [m.decode('utf-8') if isinstance(m, bytes) else m for m in memberOf]
        if group_dn not in memberOf:
            users_to_purge.append(dn)
    return users_to_purge

def delete_users(conn, users):
    """
    Delete each user (by DN) from the LDAP directory.
    """
    for dn in users:
        try:
            conn.delete_s(dn)
            print(f"Deleted user: {dn}")
        except ldap.LDAPError as e:
            print(f"Error deleting user {dn}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Purge LDAP users not in the specified group.")
    parser.add_argument("groupname", help="Name of the group whose members should be retained")
    args = parser.parse_args()
    
    config = load_config()
    base_dn = get_base_dn(config)
    conn = get_ldap_connection(config)
    
    group_dn = get_group_dn(conn, base_dn, args.groupname)
    print(f"Group DN for '{args.groupname}': {group_dn}")
    
    users_to_purge = find_users_to_purge(conn, base_dn, group_dn)
    if not users_to_purge:
        print("No users found that are not members of the group.")
        sys.exit(0)
    
    print("The following users are not members of the group:")
    for user in users_to_purge:
        print(user)
    
    confirm = input("Purge these users? [N/y]: ").strip().lower()
    if confirm in ['y', 'yes']:
        delete_users(conn, users_to_purge)
    else:
        print("Aborting purge operation.")

if __name__ == '__main__':
    main()
