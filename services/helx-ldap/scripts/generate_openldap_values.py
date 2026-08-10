#!/usr/bin/env python

import yaml

def load_ldap_config(config_file="helx_ldap_config.yaml"):
    """Load LDAP config from helx_ldap_config.yaml."""
    with open(config_file, "r") as file:
        return yaml.safe_load(file)

def generate_helm_values(config):
    """Generate Helm openldap_values.yaml for OpenLDAP based on the LDAP config."""
    admin_password = config['ldap']['admin']['password']
    config_password = config['ldap']['config']['password']

    helm_values = {
        'replicaCount': 1,
        'global': {
            'adminPassword': admin_password,
            'configPassword': config_password
        },
        'persistence': {
            'enabled': True
        },
        'replication': {
            'enabled': False
        }
    }

    # Write the Helm values to openldap_values.yaml
    with open("openldap_values.yaml", "w") as helm_file:
        yaml.dump(helm_values, helm_file, default_flow_style=False)

    print("openldap_values.yaml has been generated.")

if __name__ == "__main__":
    # Load LDAP config and generate Helm values
    ldap_config = load_ldap_config()
    generate_helm_values(ldap_config)
