# Variables for repository and tag.
REPO ?= containers.renci.org/helxplatform/ordrd-group-x
TAG ?= latest

.PHONY: docs build push

# Generate or update Swagger documentation.
docs:
	swag init -g main.go

# Build the Docker image.
# The build target depends on docs.
build: docs
	docker build --platform=linux/amd64 -t $(REPO):$(TAG) .

# Push the Docker image to the repository.
push:
	docker push $(REPO):$(TAG)
