SHELL 			 := /bin/bash
BRANCH_NAME	 	 := $(shell git branch --show-current | sed -r 's/[/]+/_/g')
VER := $(shell uuidgen | tail -c 13)
VERSION := v1.1.1
# For dev version tag we use the git branch 
# with 12 chars from unique uuid.
DEV_VERSION := ${BRANCH_NAME}-${VER}
DOCKER_REGISTRY := containers.renci.org
DOCKER_OWNER    := helxplatform
DOCKER_APP      := appstore-sockets
DOCKER_IMAGE    := ${DOCKER_OWNER}/${DOCKER_APP}/server
DOCKER_MONITORING_IMAGE	:=	${DOCKER_OWNER}/${DOCKER_APP}/monitoring

help:
	@grep -E '^#[a-zA-Z\.\-]+:.*$$' $(MAKEFILE_LIST) | tr -d '#' | awk 'BEGIN {FS = ": "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

init:
	git --version
	echo "Please make sure your git version is greater than 2.9.0. If it's not, this command will fail."
	git config --local core.hooksPath .githooks/

#build.dev: Used for local image builds and fast testing, supporting user supplied version. 
build.dev:
	echo "Building docker image: $(DOCKER_IMAGE):$(DEV_VERSION)"
	docker build --platform=linux/amd64 --no-cache --pull -t $(DOCKER_IMAGE):$(DEV_VERSION) -f Dockerfile .
	docker tag $(DOCKER_IMAGE):$(DEV_VERSION) $(DOCKER_REGISTRY)/$(DOCKER_IMAGE):$(DEV_VERSION)
	echo "Building docker image: $(DOCKER_MONITORING_IMAGE):$(DEV_VERSION)"
	docker build --platform=linux/amd64 --no-cache --pull -t $(DOCKER_MONITORING_IMAGE):$(DEV_VERSION) -f monitoring/Dockerfile ./monitoring/
	docker tag $(DOCKER_MONITORING_IMAGE) $(DOCKER_REGISTRY)/$(DOCKER_MONITORING_IMAGE):$(DEV_VERSION)

#build.prod: For use with ci/cd or building production image based on VERSION set in makefile.
build.prod:
	echo "Building docker image: $(DOCKER_IMAGE):$(VERSION)"
	docker build --platform=linux/amd64 --no-cache --pull -t $(DOCKER_IMAGE):$(VERSION) -f Dockerfile .
	docker tag $(DOCKER_IMAGE) $(DOCKER_REGISTRY)/$(DOCKER_IMAGE):$(VERSION)
	echo "Building docker image: $(DOCKER_MONITORING_IMAGE):$(VERSION)"
	docker build --platform=linux/amd64 --no-cache --pull -t $(DOCKER_MONITORING_IMAGE):$(VERSION) -f monitoring/Dockerfile ./monitoring/
	docker tag $(DOCKER_MONITORING_IMAGE) $(DOCKER_REGISTRY)/$(DOCKER_MONITORING_IMAGE):$(VERSION)

publish.dev:
	docker image push $(DOCKER_REGISTRY)/$(DOCKER_IMAGE):$(DEV_VERSION)
	docker image push $(DOCKER_REGISTRY)/$(DOCKER_MONITORING_IMAGE):$(DEV_VERSION)

publish.prod:
	docker image push $(DOCKER_REGISTRY)/$(DOCKER_IMAGE):$(VERSION)
	docker image push $(DOCKER_REGISTRY)/$(DOCKER_MONITORING_IMAGE):$(VERSION)
