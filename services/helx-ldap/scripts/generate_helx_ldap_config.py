#!/usr/bin/env python

import yaml
import random
import string
from getpass import getpass

def generate_random_password(length=10):
    """Generates a random password of given length without punctuation."""
    characters = string.ascii_letters + string.digits  # No punctuation
    return ''.join(random.choice(characters) for i in range(length))

def prompt_with_default(prompt_text, default_value):
    """
    Prompt the user for input, and return the default if no input is given.
    """
    user_input = input(f"{prompt_text} [{default_value}]: ")
    return user_input.strip() if user_input else default_value

def prompt_password_with_default(prompt_text, default_password):
    """
    Prompt the user for a password with the option to accept a generated default.
    """
    user_input = getpass(f"{prompt_text} [default: {default_password}]: ")
    return user_input.strip() if user_input else default_password

def generate_ldap_config():
    """
    Generate helx_ldap_config.yaml based on user input or defaults, with random 
    password generation.
    """
    print("HElX LDAP Configuration Setup")

    # Default values
    default_server_url = "ldap://localhost:5389"
    default_admin_dn = "cn=admin,dc=example,dc=org"
    default_config_dn = "cn=admin,cn=config"

    # Generate random passwords as defaults
    default_admin_password = generate_random_password()
    default_config_password = generate_random_password()

    # Ask for input with defaults
    server_url = prompt_with_default("LDAP Server URL", default_server_url)
    admin_dn = prompt_with_default("Admin Bind DN", default_admin_dn)
    config_dn = prompt_with_default("Config DN", default_config_dn)

    # Prompt for passwords with generated defaults
    admin_password = prompt_password_with_default("Admin Password", default_admin_password)
    config_password = prompt_password_with_default("Config Password", default_config_password)

    # Construct the configuration dictionary
    ldap_config = {
        'ldap': {
            'server_url': server_url,
            'admin': {
                'bind_dn': admin_dn,
                'password': admin_password,
            },
            'config': {
                'dn': config_dn,
                'password': config_password,
            }
        }
    }

    # Write to helx_ldap_config.yaml
    with open("helx_ldap_config.yaml", "w") as yaml_file:
        yaml.dump(ldap_config, yaml_file, default_flow_style=False)

    print("\nHElX LDAP configuration has been saved to 'helx_ldap_config.yaml'.")

if __name__ == "__main__":
    generate_ldap_config()
