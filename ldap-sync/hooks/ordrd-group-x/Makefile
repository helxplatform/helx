# Makefile

# Default repository and tag; override by passing REPO or TAG as needed.
REPO ?= containers.renci.org/helxplatform
TAG ?= latest
IMAGE := $(REPO)/ordrd-group-x:$(TAG)

.PHONY: docs build push

# Generate or update Swagger docs using swaggo.
docs:
	swag init -g main.go

# Build the Docker image (platform linux/amd64) after updating docs.
build: docs
	docker build --platform linux/amd64 -t $(IMAGE) .

# Push the Docker image to the repository.
push: build
	docker push $(IMAGE)
