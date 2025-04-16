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
openldap_values.yaml: $(CONFIG_FILE) scripts/generate_openldap_values.py
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
	@# Extract the namespace from the config file and deploy
	@NAMESPACE=$$(python3 -c "import yaml; print(yaml.safe_load(open('$(CONFIG_FILE)'))['namespace'])") && \
	echo "Deploying OpenLDAP with Helm to namespace: $$NAMESPACE" && \
	helm install openldap openldap/openldap-stack-ha -f openldap_values.yaml -n $$NAMESPACE
	@echo "OpenLDAP has been deployed."

# Apply the memberOf overlay using the generated script
apply_memberof:
	@echo "Applying memberOf overlay..."
	python3 scripts/apply_configs.py config/memberof

allow_anon:
	@echo "Applying Kubernetes service account LDIFs..."
	python3 scripts/apply_configs.py config/anon

apply_helx_user:
	@echo "Applying Kubernetes service account LDIFs..."
	python3 scripts/apply_configs.py config/helxUser

# Apply all configurations
configure: apply_memberof allow_anon apply_helx_user
	@echo "All configurations have been applied."

# Create Kubernetes secret with admin password
user_mutator_secret:
	@echo "Creating Kubernetes secret user-mutator-ldap-password..."
	@NAMESPACE=$$(python3 -c "import yaml; config = yaml.safe_load(open('$(CONFIG_FILE)')); print(config['namespace'])") && \
	PASSWORD=$$(python3 -c "import yaml; config = yaml.safe_load(open('$(CONFIG_FILE)')); print(config['ldap']['admin']['password'])") && \
	kubectl create secret generic user-mutator-ldap-password --from-literal=password=$$PASSWORD -n $$NAMESPACE
	@echo "Kubernetes secret 'user-mutator-ldap-password' has been created in namespace $$NAMESPACE."

# Check if Python is installed
check-python:
	@if ! command -v $(PYTHON) &> /dev/null; then \
		echo "Python3 could not be found. Please install it to proceed."; \
		exit 1; \
	fi

# Install dependencies (if any)
install-deps:
	@echo "Installing dependencies..."
	@pip3 install -r requirements.txt

# Clean target to remove the generated YAML file
clean:
	@echo "Cleaning up..."
	@rm -f $(CONFIG_FILE)
	@rm -f openldap_values.yaml

# Phony targets
.PHONY: all clean check-python install-deps
