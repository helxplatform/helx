SHELL 			 := /bin/bash
BRANCH_NAME	 	 := $(shell git branch --show-current | sed -r 's/[/]+/_/g')
override VERSION := ${BRANCH_NAME}-${VER}
DEFAULT_REGISTRY := containers.renci.org
DOCKER_REGISTRY := ${DEFAULT_REGISTRY}
DOCKER_OWNER    := helxplatform
DOCKER_APP      := appstore-sockets
DOCKER_TAG   	:= ${VERSION}
DOCKER_IMAGE    := ${DOCKER_OWNER}/${DOCKER_APP}/server:$(DOCKER_TAG)
DOCKER_MONITORING_IMAGE	:=	${DOCKER_OWNER}/${DOCKER_APP}/monitoring:$(DOCKER_TAG)

help:
	@grep -E '^#[a-zA-Z\.\-]+:.*$$' $(MAKEFILE_LIST) | tr -d '#' | awk 'BEGIN {FS = ": "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

init:
	git --version
	echo "Please make sure your git version is greater than 2.9.0. If it's not, this command will fail."
	git config --local core.hooksPath .githooks/

#build.image: build project docker image
build.image:
	if [ -z "$(VER)" ]; then echo "Please provide a value for the VER variable like this:"; echo "make VER=4 build.image"; false; fi;
	echo "Building docker image: $(DOCKER_IMAGE)"
	docker build --platform=linux/amd64 --no-cache --pull -t $(DOCKER_IMAGE) -f Dockerfile .
	docker tag ${DOCKER_IMAGE} ${DOCKER_REGISTRY}/${DOCKER_IMAGE}

build.monitoring:
	if [ -z "$(VER)" ]; then echo "Please provide a value for the VER variable like this:"; echo "make VER=4 build.image"; false; fi;
	echo "Building docker image: $(DOCKER_MONITORING_IMAGE)"
	docker build --platform=linux/amd64 --no-cache --pull -t $(DOCKER_MONITORING_IMAGE) -f monitoring/Dockerfile ./monitoring/
	docker tag ${DOCKER_MONITORING_IMAGE} ${DOCKER_REGISTRY}/${DOCKER_MONITORING_IMAGE}

publish: build
	if [ -z "$(VER)" ]; then echo "Please provide a value for the VER variable like this:"; echo "make VER=4 build.image"; false; fi;
	docker image push $(DOCKER_REGISTRY)/$(DOCKER_IMAGE)
	docker image push ${DOCKER_REGISTRY}/${DOCKER_MONITORING_IMAGE}

build: build.image build.monitoring

clean:
	rm -rf build
	rm -rf node_modules