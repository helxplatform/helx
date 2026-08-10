# Variables
PYTHON := python3
SCRIPT := scripts/generate_helx_ldap_config.py
CONFIG_FILE := helx_ldap_config.yaml

# Default target
all: $(CONFIG_FILE)

# Target to generate helx_ldap_config.yaml
$(CONFIG_FILE): $(SCRIPT)
	@echo "Generating $(CONFIG_FILE)..."
	$(PYTHON) $(SCRIPT)
	@echo "$(CONFIG_FILE) has been generated."

# Generate openldap_values.yaml using Python script
openldap_values.yaml: helx_ldap_config.yaml scripts/generate_openldap_values.py
	@echo "Generating openldap_values.yaml..."
	scripts/generate_openldap_values.py

# Add the OpenLDAP Helm repository
helm_repo_add:
	@echo "Adding the OpenLDAP Helm repository..."
	helm repo add openldap https://jp-gouin.github.io/helm-openldap/
	helm repo update
	@echo "Helm repository added and updated."

# Deploy OpenLDAP using the generated values file
helm_deploy: openldap_values.yaml
	@echo "Deploying OpenLDAP with Helm..."
	helm install openldap openldap/openldap-stack-ha -f openldap_values.yaml
	@echo "OpenLDAP has been deployed."

# Apply the memberOf overlay using the generated script
apply_memberof:
	@echo "Applying memberOf overlay..."
	python3 scripts/apply_ldif_files.py ldif/memberof

apply_kubernetes_sc:
	@echo "Applying Kubernetes service account LDIFs..."
	python3 scripts/apply_ldif_files.py ldif/kubernetesSC

# Check if Python is installed
check-python:
	@if ! command -v $(PYTHON) &> /dev/null; then \
		echo "Python3 could not be found. Please install it to proceed."; \
		exit 1; \
	fi

# Install dependencies (if any)
install-deps:
	@echo "Installing dependencies..."
	@pip3 install pyyaml

# Clean target to remove the generated YAML file
clean:
	@echo "Cleaning up..."
	@rm -f $(CONFIG_FILE)
	@rm -f openldap_values.yaml

# Phony targets
.PHONY: all clean check-python install-deps
