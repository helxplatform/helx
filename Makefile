SHELL := /bin/bash
# 10MB
MAX_SUBTREE_BLOB_BYTES ?= 10000000

# Git remotes used by the services/ git subtrees.
APPSTORE_URL                    ?= https://github.com/helxplatform/appstore.git
APPSTORE_CHART_URL              ?= https://github.com/helxplatform/appstore-chart.git
APPSTORE_PREPULLER_URL          ?= https://github.com/helxplatform/appstore-prepuller.git
APPSTORE_SOCKETS_URL            ?= https://github.com/helxplatform/appstore-sockets.git
APPSTORE_SOCKETS_CHART_URL      ?= https://github.com/helxplatform/appstore-sockets-chart.git
HELX_LDAP_URL                   ?= https://github.com/helxplatform/helx-ldap.git
LDAP_SYNC_URL                   ?= https://github.com/helxplatform/ldap-sync.git
UI_URL                          ?= https://github.com/helxplatform/helx-ui.git
UI_CHART_URL                    ?= https://github.com/helxplatform/ui-chart.git
USER_MUTATOR_URL                ?= https://github.com/helxplatform/user-mutator.git

# Branches and prefixes used when the subtrees are added or pulled.
APPSTORE_PREFIX                 ?= services/appstore
APPSTORE_BRANCH                 ?= develop
APPSTORE_CHART_PREFIX           ?= services/appstore/chart
APPSTORE_CHART_BRANCH           ?= main
APPSTORE_PREPULLER_PREFIX       ?= services/appstore-prepuller
APPSTORE_PREPULLER_BRANCH       ?= main
APPSTORE_SOCKETS_PREFIX         ?= services/appstore-sockets
APPSTORE_SOCKETS_BRANCH         ?= master
APPSTORE_SOCKETS_CHART_PREFIX   ?= services/appstore-sockets/chart
APPSTORE_SOCKETS_CHART_BRANCH   ?= master
HELX_LDAP_PREFIX                ?= services/helx-ldap
HELX_LDAP_BRANCH                ?= develop
LDAP_SYNC_PREFIX                ?= services/ldap-sync
LDAP_SYNC_BRANCH                ?= master
UI_PREFIX                       ?= services/ui
UI_BRANCH                       ?= develop
UI_CHART_PREFIX                 ?= services/ui/chart
UI_CHART_BRANCH                 ?= master
USER_MUTATOR_PREFIX             ?= services/user-mutator
USER_MUTATOR_BRANCH             ?= develop

# Vendored charts. helxplatform/helx-chart keeps several charts as
# subdirectories, and git subtree cannot map a remote subdirectory to a local
# prefix, so these are mirrored by content instead of merged. Local edits to a
# mirrored chart are overwritten on the next pull.
HELX_CHART_URL                  ?= https://github.com/helxplatform/helx-chart.git
HELX_CHART_BRANCH               ?= master
# Destination for each mirrored chart. `ambassador` also lives upstream and can
# be mirrored by adding a prefix, a pull-ambassador target, and a pull-helx-chart
# prerequisite.
RESTY_CHART_PREFIX              ?= services/resty/chart
POD_REAPER_CHART_PREFIX         ?= services/pod-reaper/chart

# The project virtualenv is the default interpreter. System pip is often
# externally managed (PEP 668) and refuses to install, so a venv is not just
# tidiness. Set PYTHON=... to use your own interpreter and skip provisioning.
VENV                            ?= .venv
BOOTSTRAP_PYTHON                ?= python3
VENV_PYTHON                     := $(VENV)/bin/python
PYTHON                          ?= $(VENV_PYTHON)
CI_REQUIREMENTS                 := .github/requirements-ci.txt
VENV_STAMP                      := $(VENV)/.ci-requirements
# Auto-provision only when the default venv interpreter is in use.
PYTHON_READY                    := $(if $(filter $(VENV_PYTHON),$(PYTHON)),$(VENV_STAMP),)

CI_SCRIPT                       ?= .github/scripts/ci.py
BUILD_CHART                     ?= .github/scripts/helm-build-chart.sh
UMBRELLA_CHART                  ?= deploy/helm/helx-chart
COMMON_CHART                    ?= deploy/helm/helx-common/chart

# Defaults for the developer-facing targets, all overridable on the command line.
BASE                            ?= develop
CHECK_VERSIONS_FLAGS            ?= --include-untracked --umbrella-above-release
CHANNEL                         ?= develop
SERVICE                         ?=
CHART_CHANNEL                   ?=
CHART_CHANNEL_COMMIT            ?=
HOOKS_PATH                      ?= .githooks

# Local image builds. SERVICES names the services you rebuilt; only those get
# pinned in the umbrella, so everything else stays on its released tag.
# SERVICES=all stands in for every service that builds an image, so the whole
# list does not have to be typed out; it cannot be mixed with service names.
SERVICES                        ?=
# Every component in .github/ci/images.yaml, sorted. Deliberately recursive:
# it shells out only when SERVICES=all asks it to, and only while a recipe is
# being expanded, by which point $(PYTHON_READY) has built the venv.
ALL_IMAGE_SERVICES               = $(shell $(PYTHON) $(CI_SCRIPT) image-plan | cut -f1 | sort -u)
# The list every target below acts on: SERVICES, with all expanded.
RESOLVED_SERVICES                = $(if $(filter all,$(SERVICES)),$(ALL_IMAGE_SERVICES),$(SERVICES))
TAG                             ?= test-$(shell git rev-parse --short=7 HEAD 2>/dev/null)
# Registry the local image targets build, push, and pin against. Empty means
# the registry in .github/ci/images.yaml, which is Harbor. Set it to a base URL
# -- host, optional port, optional project path -- to use your own instead:
#   IMAGE_REGISTRY=myregistry.azurecr.io/helxplatform
#   IMAGE_REGISTRY=localhost:5000
# Images live under the registry's 'helxplatform' project, so an override
# that omits it warns -- loudly, but it still builds, in case you meant it.
# A localhost registry is exempt: those serve from their root by convention.
# Any http:// or https:// prefix is dropped, since an image reference has no
# scheme. Use the same value for build, push, and ci-build-helx-chart, or the
# packaged chart will point somewhere the images were never pushed.
IMAGE_REGISTRY                  ?=
# Passed to every ci.py image-plan call, so one registry override reaches the
# build, load, and push targets identically.
IMAGE_PLAN_FLAGS                 = --services "$(RESOLVED_SERVICES)" \
                                   $(if $(IMAGE_REGISTRY),--registry "$(IMAGE_REGISTRY)")
# Architecture the local image targets build for. CI builds linux/amd64 only
# (.github/actions/build-service pins `platforms: linux/amd64`), so that is the
# default here too: without it, `docker build` on an Apple Silicon Mac produces
# a linux/arm64 image that dies with "exec format error" on an amd64 node.
# Override it when the target is not amd64 -- notably a local kind/minikube/k3d
# cluster on Apple Silicon, which wants IMAGE_PLATFORM=linux/arm64.
IMAGE_PLATFORM                  ?= linux/amd64
# Where the local chart targets leave packaged archives, next to a pointer file
# naming the archive each build produced. Only the local targets set this; CI
# reads the path out of $$GITHUB_OUTPUT and keeps using a scratch directory.
CHART_DIST                      ?= dist/charts
# The pointer ci-build-helx-chart writes and ci-helm-deploy reads. It is named
# after the chart directory because that is the one part of the archive's
# identity known before the build runs -- a candidate build derives its version
# from the channel and commit, so the file name is not predictable.
UMBRELLA_PACKAGE_POINTER         = $(CHART_DIST)/.$(notdir $(UMBRELLA_CHART)).path
# Release ci-helm-deploy installs or upgrades, and where it puts it. An empty
# NAMESPACE means whatever namespace the current kubectl context selects; if the
# context selects none either, the deploy stops rather than assuming 'default'.
RELEASE                         ?= helx
NAMESPACE                       ?=
# Values files for ci-helm-deploy, space separated; each is passed as one -f.
# These are applied after LOCAL_VALUES_FILE's, so they win on any shared key.
VALUES                          ?=
# Untracked list of local values files, one path per line. A relative path is
# relative to the repository root, and a leading ~/ is expanded to $$HOME --
# the shell never sees these paths, so nothing else expands for them. Blank
# lines and # comments are ignored. Missing entries warn and ask before
# deploying rather than silently leaving values out.
LOCAL_VALUES_FILE               ?= deploy/local-dev/local-values-files.env
# Answer that confirmation prompt -- and the one ci-uninstall-release always
# asks -- in advance, for a non-interactive run.
ASSUME_YES                      ?=
# Anything else to hand helm, e.g. HELM_FLAGS="--dry-run --debug"
HELM_FLAGS                      ?=
# What ci-uninstall-release deletes once the release itself is gone. helm
# uninstall leaves every one of these behind: the Secrets are chart-managed and
# annotated helm.sh/resource-policy: keep, the appstore and user storage claims
# carry that same annotation, and the data-* claims come from StatefulSet
# volumeClaimTemplates, which helm never owned in the first place. Names the
# charts build out of the release name are written with $(RELEASE); the rest are
# fixed by whichever chart creates them. Set either variable empty to leave that
# kind of resource alone.
UNINSTALL_PVCS                  ?= appstore-postgresql-pvc \
                                   stdnfs \
                                   data-$(RELEASE)-postgresql-0 \
                                   data-$(RELEASE)-ldap-sync-postgres-0 \
                                   data-openldap-0
UNINSTALL_SECRETS               ?= $(RELEASE)-appstore-secrets \
                                   $(RELEASE)-appstore-sockets \
                                   $(RELEASE)-ldap-sync-secrets \
                                   $(RELEASE)-postgresql \
                                   openldap-credentials \
                                   pgadmin-env
# make help and its topic targets are generated from the comments above each
# target, so documentation cannot drift from what it documents. See the header
# of $(HELP_AWK) for the markers involved.
HELP_AWK                         = deploy/local-dev/make-help.awk
THIS_MAKEFILE                    = $(firstword $(MAKEFILE_LIST))
# auto picks whichever of kind, minikube, or k3d is installed.
CLUSTER_TOOL                    ?= auto
CLUSTER_NAME                    ?=

.DEFAULT_GOAL := help

# Every target here mutates the same git repository -- the index lock,
# FETCH_HEAD, and subtree merges are all shared -- so nothing in this file is
# safe to run concurrently. GNU make 3.81 (the make macOS ships) ignores any
# prerequisites given to .NOTPARALLEL and serializes the whole file regardless,
# so this is stated bare: it is exactly what already happens, and it keeps the
# same meaning on make 4.4+, where a prerequisite list would silently narrow it
# to only the listed targets' prerequisites.
.NOTPARALLEL:

.PHONY: help help-subtrees help-ci help-locks help-all-vars \
        setup add-remotes add-subtrees \
        add-subtree-appstore \
        add-subtree-appstore-chart \
        add-subtree-appstore-prepuller \
        add-subtree-appstore-sockets \
        add-subtree-appstore-sockets-chart \
        add-subtree-helx-ldap \
        add-subtree-ldap-sync \
        add-subtree-ui \
        add-subtree-ui-chart \
        add-subtree-user-mutator \
        pull-appstore \
        pull-appstore-chart \
        pull-appstore-prepuller \
        pull-appstore-sockets \
        pull-appstore-sockets-chart \
        pull-helx-ldap \
        pull-ldap-sync \
        pull-ui \
        pull-ui-chart \
        pull-user-mutator \
        pull-helx-chart \
        pull-resty \
        pull-pod-reaper \
        pull-remotes pull-subtree \
        sync-locks \
        sync-helx-lock \
        check-locks \
        ci-pip-install \
        ci-validate-everything \
        ci-check-versions \
        ci-tests \
        ci-build-chart \
        ci-locked-deps \
        ci-candidate-version \
        ci-build-helx-chart \
        ci-build-common-chart \
        ci-build-helx-images \
        ci-load-helx-images \
        ci-push-helx-images \
        ci-helm-deploy \
        ci-uninstall-release \
        docker-build \
        pre-push \
        install-hooks

#help: Show repository setup and index the other help topics
help:
	@echo 'HeLx monorepo. Targets are grouped by topic; run the help target'
	@echo 'for a group to see what it contains.'
	@echo
	@awk -f $(HELP_AWK) -v topic=setup $(THIS_MAKEFILE)
	@echo
	@echo 'More help:'
	@echo '  make help-subtrees    Pulling service subtrees, mirroring vendored charts'
	@echo '  make help-ci          Checks, chart and image builds, and local deploys'
	@echo '  make help-locks       Regenerating and verifying Chart.lock files'
	@echo '  make help-all-vars    Every variable those targets accept'

#help-subtrees: Show subtree pulls and the vendored chart mirrors
help-subtrees:
	@awk -f $(HELP_AWK) -v topic=subtrees $(THIS_MAKEFILE)
	@echo
	@echo 'Every variable these accept: make help-all-vars'

#help-ci: Show the CI-shaped checks, builds, and local deploy flow
help-ci:
	@awk -f $(HELP_AWK) -v topic=ci $(THIS_MAKEFILE)
	@echo
	@echo 'Every variable these accept: make help-all-vars'

#help-locks: Show Chart.lock maintenance
help-locks:
	@awk -f $(HELP_AWK) -v topic=locks $(THIS_MAKEFILE)
	@echo
	@echo 'Every variable these accept: make help-all-vars'

#help-all-vars: Show every variable the targets accept
help-all-vars:
	@echo 'Environment variables:'
	@echo '  PYTHON=<path>          Interpreter to use (default $(VENV_PYTHON); skips venv setup)'
	@echo '  VENV=<dir>             Virtualenv location (default .venv)'
	@echo '  SERVICE=<name>         Required by the per-service targets (make help-ci)'
	@echo '  SERVICES="a b"         Services you rebuilt locally; only these get pinned'
	@echo '  SERVICES=all           Every service that builds an image, without listing them'
	@echo '  TAG=<tag>              Image tag to build, push, and pin (default test-<short-sha>)'
	@echo '  IMAGE_REGISTRY=<url>   Build, push, and pin against this registry instead'
	@echo '                         of Harbor, e.g. myregistry.azurecr.io/helx'
	@echo '  IMAGE_PLATFORM=<arch>  Architecture to build for (default linux/amd64, as CI'
	@echo '                         publishes); linux/arm64 for a local cluster on Apple Silicon'
	@echo '  CLUSTER_TOOL=<tool>    kind, minikube, k3d, or auto (default auto)'
	@echo '  CLUSTER_NAME=<name>    Cluster to load into, when your tool needs it'
	@echo '  RELEASE=<name>         Release ci-helm-deploy installs or upgrades (default helx);'
	@echo '                         ci-uninstall-release requires it to be named explicitly'
	@echo '  NAMESPACE=<ns>         Namespace to deploy into or uninstall from (default: the'
	@echo '                         kubectl context'"'"'s; required when the context selects none)'
	@echo '  VALUES="a.yaml b.yaml" Extra values files for ci-helm-deploy, applied last'
	@echo '  LOCAL_VALUES_FILE=<f>  Untracked list of values files, one path per line'
	@echo '                         (default deploy/local-dev/local-values-files.env)'
	@echo '  UNINSTALL_PVCS="a b"   Claims ci-uninstall-release deletes once the release is'
	@echo '                         gone (default: the postgres, openldap, and shared storage'
	@echo '                         claims helm uninstall keeps)'
	@echo '  UNINSTALL_SECRETS="a"  Secrets it deletes as well (default: the chart-managed'
	@echo '                         ones annotated helm.sh/resource-policy: keep)'
	@echo '  ASSUME_YES=1           Skip the confirmation prompt a missing file triggers, and'
	@echo '                         the one ci-uninstall-release always asks'
	@echo '  HELM_FLAGS=<flags>     Extra helm arguments, e.g. --dry-run --debug'
	@echo '  CHART_DIST=<dir>       Where packaged charts land (default dist/charts)'
	@echo '  BASE=<ref>             Base revision for ci-check-versions (default develop)'
	@echo '  CHECK_VERSIONS_FLAGS=  Defaults to --include-untracked --umbrella-above-release,'
	@echo '                         matching CI for a pull request into develop. Set empty for'
	@echo '                         the strict default-branch rules.'
	@echo '  CHANNEL=<name>         Candidate channel name (default develop)'
	@echo '  CHART_CHANNEL=<name>   Build the umbrella as a candidate for this channel'
	@echo '  CHART_CHANNEL_COMMIT=  Commit whose images the candidate pins (default HEAD)'
	@echo '  FORCE=1                Let the chart mirrors overwrite uncommitted work'
	@echo
	@echo 'Target groups: make help'

##@ setup Repository setup
# setup: Add all remotes and missing service subtrees, plus install git hooks
setup: add-subtrees install-hooks

# ensure-remote: Add a remote, or verify that an existing one has the expected URL.
define ensure-remote
	@if git remote get-url "$(1)" >/dev/null 2>&1; then \
		if test "$$(git remote get-url "$(1)")" != "$(2)"; then \
			echo "Remote $(1) already exists with an unexpected URL:"; \
			git remote get-url "$(1)"; \
			echo "Expected: $(2)"; \
			exit 1; \
		fi; \
		echo "Remote $(1) already exists"; \
	else \
		echo "Adding remote $(1) -> $(2)"; \
		git remote add "$(1)" "$(2)"; \
	fi
endef

# check-incoming: refuse to pull a subtree whose incoming tree has oversized files.
# $(1)=remote  $(2)=branch
define check-incoming
	@git fetch -q "$(1)" "$(2)"; \
	oversized=$$(git ls-tree -r -l FETCH_HEAD | awk -v m=$(MAX_SUBTREE_BLOB_BYTES) '$$4 > m {printf "    %10d  %s\n", $$4, $$5}'); \
	if [ -n "$$oversized" ]; then \
		echo "REFUSING to pull $(1)/$(2) -- incoming tree has files over $(MAX_SUBTREE_BLOB_BYTES) bytes:"; \
		echo "$$oversized"; \
		echo "  Fix upstream (git rm + .gitignore), then retry."; \
		exit 1; \
	fi
endef

# add-remotes: Add or verify all remotes needed by the service subtrees
add-remotes:
	$(call ensure-remote,helx-chart,$(HELX_CHART_URL))
	$(call ensure-remote,appstore,$(APPSTORE_URL))
	$(call ensure-remote,appstore-chart,$(APPSTORE_CHART_URL))
	$(call ensure-remote,appstore-prepuller,$(APPSTORE_PREPULLER_URL))
	$(call ensure-remote,appstore-sockets,$(APPSTORE_SOCKETS_URL))
	$(call ensure-remote,appstore-sockets-chart,$(APPSTORE_SOCKETS_CHART_URL))
	$(call ensure-remote,helx-ldap,$(HELX_LDAP_URL))
	$(call ensure-remote,ldap-sync,$(LDAP_SYNC_URL))
	$(call ensure-remote,ui,$(UI_URL))
	$(call ensure-remote,ui-chart,$(UI_CHART_URL))
	$(call ensure-remote,user-mutator,$(USER_MUTATOR_URL))

# add-subtree: Add a subtree unless its prefix is already present.
define add-subtree
	@if test -e "$(1)"; then \
		echo "Subtree $(1) already exists; skipping"; \
	else \
		echo "Adding $(2)/$(3) at $(1)"; \
		git subtree add --prefix="$(1)" "$(2)" "$(3)"; \
	fi
endef

# add-subtrees: Add all missing service subtrees
add-subtrees: add-remotes \
	add-subtree-appstore \
	add-subtree-appstore-chart \
	add-subtree-appstore-prepuller \
	add-subtree-appstore-sockets \
	add-subtree-appstore-sockets-chart \
	add-subtree-helx-ldap \
	add-subtree-ldap-sync \
	add-subtree-ui \
	add-subtree-ui-chart \
	add-subtree-user-mutator

##@ subtrees Adding a single subtree
# add-subtree-appstore: Add the appstore subtree
add-subtree-appstore: add-remotes
	$(call add-subtree,$(APPSTORE_PREFIX),appstore,$(APPSTORE_BRANCH))

# add-subtree-appstore-chart: Add the appstore Helm chart subtree.
add-subtree-appstore-chart: add-remotes
	$(call add-subtree,$(APPSTORE_CHART_PREFIX),appstore-chart,$(APPSTORE_CHART_BRANCH))

# add-subtree-appstore-prepuller: Add the appstore-prepuller subtree
add-subtree-appstore-prepuller: add-remotes
	$(call add-subtree,$(APPSTORE_PREPULLER_PREFIX),appstore-prepuller,$(APPSTORE_PREPULLER_BRANCH))

# add-subtree-appstore-sockets: Add the appstore-sockets subtree
add-subtree-appstore-sockets: add-remotes
	$(call add-subtree,$(APPSTORE_SOCKETS_PREFIX),appstore-sockets,$(APPSTORE_SOCKETS_BRANCH))

# add-subtree-appstore-sockets-chart: Add the appstore-sockets Helm chart subtree
add-subtree-appstore-sockets-chart: add-remotes
	$(call add-subtree,$(APPSTORE_SOCKETS_CHART_PREFIX),appstore-sockets-chart,$(APPSTORE_SOCKETS_CHART_BRANCH))

# add-subtree-helx-ldap: Add the helx-ldap subtree
add-subtree-helx-ldap: add-remotes
	$(call add-subtree,$(HELX_LDAP_PREFIX),helx-ldap,$(HELX_LDAP_BRANCH))

# add-subtree-ldap-sync: Add the ldap-sync subtree
add-subtree-ldap-sync: add-remotes
	$(call add-subtree,$(LDAP_SYNC_PREFIX),ldap-sync,$(LDAP_SYNC_BRANCH))

# add-subtree-ui: Add the UI subtree
add-subtree-ui: add-remotes
	$(call add-subtree,$(UI_PREFIX),ui,$(UI_BRANCH))

# add-subtree-ui-chart: Add the UI Helm chart subtree
add-subtree-ui-chart: add-remotes
	$(call add-subtree,$(UI_CHART_PREFIX),ui-chart,$(UI_CHART_BRANCH))

# add-subtree-user-mutator: Add the user-mutator subtree
add-subtree-user-mutator: add-remotes
	$(call add-subtree,$(USER_MUTATOR_PREFIX),user-mutator,$(USER_MUTATOR_BRANCH))

##@ subtrees Subtree updates
# pull-subtree: Pull one subtree using REMOTE, PREFIX, and BRANCH variables.
pull-subtree: add-remotes
	@if test -z "$(REMOTE)" || test -z "$(PREFIX)" || test -z "$(BRANCH)"; then \
		echo "Usage: make pull-subtree REMOTE=<remote> PREFIX=<path> BRANCH=<branch>"; \
		exit 1; \
	fi
	$(call check-incoming,$(REMOTE),$(BRANCH))
	git subtree pull --prefix="$(PREFIX)" "$(REMOTE)" "$(BRANCH)"

# pull-appstore: Pull the latest configured appstore branch into its subtree
pull-appstore: add-remotes
	$(call check-incoming,appstore,$(APPSTORE_BRANCH))
	git subtree pull --prefix="$(APPSTORE_PREFIX)" appstore "$(APPSTORE_BRANCH)"

# pull-appstore-chart: Pull the latest configured appstore chart branch
pull-appstore-chart: add-remotes
	$(call check-incoming,appstore-chart,$(APPSTORE_CHART_BRANCH))
	git subtree pull --prefix="$(APPSTORE_CHART_PREFIX)" appstore-chart "$(APPSTORE_CHART_BRANCH)"

# pull-appstore-prepuller: Pull the latest configured appstore-prepuller branch
pull-appstore-prepuller: add-remotes
	$(call check-incoming,appstore-prepuller,$(APPSTORE_PREPULLER_BRANCH))
	git subtree pull --prefix="$(APPSTORE_PREPULLER_PREFIX)" appstore-prepuller "$(APPSTORE_PREPULLER_BRANCH)"

# pull-appstore-sockets: Pull the latest configured appstore-sockets branch
pull-appstore-sockets: add-remotes
	$(call check-incoming,appstore-sockets,$(APPSTORE_SOCKETS_BRANCH))
	git subtree pull --prefix="$(APPSTORE_SOCKETS_PREFIX)" appstore-sockets "$(APPSTORE_SOCKETS_BRANCH)"

# pull-appstore-sockets-chart: Pull the latest configured appstore-sockets chart branch
pull-appstore-sockets-chart: add-remotes
	$(call check-incoming,appstore-sockets-chart,$(APPSTORE_SOCKETS_CHART_BRANCH))
	git subtree pull --prefix="$(APPSTORE_SOCKETS_CHART_PREFIX)" appstore-sockets-chart "$(APPSTORE_SOCKETS_CHART_BRANCH)"

# pull-helx-ldap: Pull the latest configured helx-ldap branch into its subtree
pull-helx-ldap: add-remotes
	$(call check-incoming,helx-ldap,$(HELX_LDAP_BRANCH))
	git subtree pull --prefix="$(HELX_LDAP_PREFIX)" helx-ldap "$(HELX_LDAP_BRANCH)"

# pull-ldap-sync: Pull the latest configured ldap-sync branch
pull-ldap-sync: add-remotes
	$(call check-incoming,ldap-sync,$(LDAP_SYNC_BRANCH))
	git subtree pull --prefix="$(LDAP_SYNC_PREFIX)" ldap-sync "$(LDAP_SYNC_BRANCH)"

# pull-ui: Pull the latest configured UI branch into its subtree
pull-ui: add-remotes
	$(call check-incoming,ui,$(UI_BRANCH))
	git subtree pull --prefix="$(UI_PREFIX)" ui "$(UI_BRANCH)"

# pull-ui-chart: Pull the latest configured UI chart branch
pull-ui-chart: add-remotes
	$(call check-incoming,ui-chart,$(UI_CHART_BRANCH))
	git subtree pull --prefix="$(UI_CHART_PREFIX)" ui-chart "$(UI_CHART_BRANCH)"

# pull-user-mutator: Pull the latest configured user-mutator branch
pull-user-mutator: add-remotes
	$(call check-incoming,user-mutator,$(USER_MUTATOR_BRANCH))
	git subtree pull --squash --prefix="$(USER_MUTATOR_PREFIX)" user-mutator "$(USER_MUTATOR_BRANCH)"

# mirror-chart: Replace one local chart with a subdirectory of the fetched tree.
# git subtree cannot map a remote subdirectory to a local prefix, so the chart is
# copied by content. Staging is populated and validated before anything local is
# removed, so a bad chart name leaves the working tree untouched.
# $(1)=upstream charts/<name>  $(2)=local destination
define mirror-chart
	@set -euo pipefail; \
	if test -z "$(FORCE)" && test -n "$$(git status --porcelain -- "$(2)" 2>/dev/null)"; then \
		echo "REFUSING to overwrite $(2) -- uncommitted changes present:"; \
		git status --short -- "$(2)"; \
		echo "  Commit or stash them, or re-run with FORCE=1."; \
		exit 1; \
	fi; \
	staging=$$(mktemp -d); \
	trap 'rm -rf "$$staging"' EXIT; \
	if ! git archive FETCH_HEAD "charts/$(1)" 2>/dev/null | tar -x --strip-components=2 -C "$$staging"; then \
		echo "REFUSING to mirror -- charts/$(1) is not in helx-chart/$(HELX_CHART_BRANCH)"; \
		exit 1; \
	fi; \
	if ! test -f "$$staging/Chart.yaml"; then \
		echo "REFUSING to mirror -- charts/$(1)/Chart.yaml is not in helx-chart/$(HELX_CHART_BRANCH)"; \
		exit 1; \
	fi; \
	rm -rf "$(2)"; \
	mkdir -p "$(2)"; \
	cp -R "$$staging"/. "$(2)"/; \
	echo "Mirrored charts/$(1) -> $(2) ($$(sed -n 's/^version: *//p' "$(2)/Chart.yaml" | tr -d '\"'))"
endef

##@ subtrees Vendored charts (mirrored by content, not git subtree)
# pull-resty: Mirror the resty chart out of helxplatform/helx-chart.
# Refuses to clobber uncommitted work; override with FORCE=1. To undo a pull:
#   git checkout HEAD -- <prefix> && git clean -fd <prefix>
pull-resty: add-remotes
	$(call check-incoming,helx-chart,$(HELX_CHART_BRANCH))
	$(call mirror-chart,resty,$(RESTY_CHART_PREFIX))

# pull-pod-reaper: Mirror the pod-reaper chart out of helxplatform/helx-chart.
pull-pod-reaper: add-remotes
	$(call check-incoming,helx-chart,$(HELX_CHART_BRANCH))
	$(call mirror-chart,pod-reaper,$(POD_REAPER_CHART_PREFIX))

# pull-helx-chart: Mirror every chart vendored from helxplatform/helx-chart
pull-helx-chart: pull-resty pull-pod-reaper
##> Local edits to these charts are overwritten; FORCE=1 skips the dirty check.

# require-pyyaml: fail with an actionable message instead of a raw traceback.
define require-pyyaml
	@$(PYTHON) -c 'import yaml' >/dev/null 2>&1 || { \
		echo "$(PYTHON) cannot import PyYAML, which $(CI_SCRIPT) requires."; \
		echo "  Install it:            $(PYTHON) -m pip install -r .github/requirements-ci.txt"; \
		echo "  Or choose another:     make PYTHON=/path/to/python $@"; \
		exit 1; \
	}
endef

# require-service: the per-service targets need SERVICE=<name>.
define require-service
	@if test -z "$(SERVICE)"; then \
		echo "SERVICE is required, for example: make $@ SERVICE=user-mutator"; \
		echo "Available services:"; ls -1 services | sed 's/^/  /'; \
		exit 1; \
	fi; \
	if test ! -d "services/$(SERVICE)"; then \
		echo "services/$(SERVICE) does not exist. Available services:"; \
		ls -1 services | sed 's/^/  /'; \
		exit 1; \
	fi
endef

# The virtualenv is provisioned from the requirements file and re-provisioned
# only when that file changes, so depending on the stamp costs a stat.
$(VENV_STAMP): $(CI_REQUIREMENTS)
	@echo "Provisioning $(VENV) from $(CI_REQUIREMENTS)"
	@$(BOOTSTRAP_PYTHON) -m venv "$(VENV)"
	@"$(VENV_PYTHON)" -m pip install --quiet --upgrade pip
	@"$(VENV_PYTHON)" -m pip install --quiet --requirement "$(CI_REQUIREMENTS)"
	@touch "$@"

##@ ci Developer checks (see README.md "DevEx")
# ci-pip-install: Create the virtualenv and install the CI requirements into it
ci-pip-install: $(VENV_STAMP)
	@echo "Ready: $(VENV_PYTHON)"
	@echo "make targets and .github/scripts/*.sh use it automatically."
	@echo "To get it in your own shell (optional): source $(VENV)/bin/activate"

# ci-validate-everything: Validate every chart, lock, .helmignore, and image definition
ci-validate-everything: $(PYTHON_READY)
	@$(PYTHON) $(CI_SCRIPT) validate-config

# ci-check-versions: Require version bumps for anything whose artifact changed
ci-check-versions: $(PYTHON_READY)
	@git rev-parse --verify --quiet "$(BASE)^{commit}" >/dev/null || { \
		echo "BASE=$(BASE) does not resolve. Try BASE=origin/develop."; exit 1; }
	@$(PYTHON) $(CI_SCRIPT) check-versions --base "$(BASE)" $(CHECK_VERSIONS_FLAGS)

# ci-tests: Run the unit tests for the CI helpers
ci-tests: $(PYTHON_READY)
	@$(PYTHON) -m unittest discover -s .github/scripts -p 'test_*.py'

##@ ci Building and inspecting one service
# ci-build-chart: Vendor dependencies, lint, and package one service chart
ci-build-chart: $(PYTHON_READY)
	$(call require-service)
	@if test ! -f "services/$(SERVICE)/chart/Chart.yaml"; then \
		echo "services/$(SERVICE)/chart has no Chart.yaml"; exit 1; \
	fi
	@PYTHON="$(PYTHON)" bash $(BUILD_CHART) "services/$(SERVICE)/chart"

# ci-locked-deps: Print one chart's resolved dependency name/version/repository tuples
ci-locked-deps: $(PYTHON_READY)
	$(call require-service)
	@$(PYTHON) $(CI_SCRIPT) locked-dependencies "services/$(SERVICE)/chart"

# ci-candidate-version: Print the chart version a candidate channel publishes under
ci-candidate-version: $(PYTHON_READY)
	@$(PYTHON) $(CI_SCRIPT) candidate-version --channel "$(CHANNEL)"

# check-services: 'all' is the whole list, so mixing it with service names means
# one of the two was not meant. Every target that reads SERVICES runs this,
# including the ones where SERVICES is optional.
define check-services
	@if test -n '$(filter all,$(SERVICES))' && test '$(words $(SERVICES))' -ne 1; then \
		echo 'SERVICES=all already covers every service; remove the other names.'; \
		exit 1; \
	fi
endef

# require-services: the local image targets act on an explicit list, so that a
# bare invocation cannot accidentally build every image in the repository.
# SERVICES=all is that list, spelled once, for when you did rebuild everything.
define require-services
	$(call check-services)
	@if test -z "$(SERVICES)"; then \
		echo 'SERVICES is required, for example: make $@ SERVICES="user-mutator ui"'; \
		echo 'Use SERVICES=all for every service listed below.'; \
		echo "Services that produce images:"; \
		$(PYTHON) $(CI_SCRIPT) image-plan | cut -f1 | sort -u | sed 's/^/  /'; \
		exit 1; \
	fi
endef

##@ ci Deploying a local build (see README.md "DevEx")
##> Set these in your shell; every target below reads them:
##>   export SERVICES="a b"              Services you rebuilt; only these get pinned (required)
##>                                      or SERVICES=all for every service that builds an image
##>   export TAG=<tag>                   Image tag to build, push, and pin (default test-<short-sha>)
##>   export IMAGE_REGISTRY=<url>        Registry to build, push, and pin against (default Harbor)
# ci-build-helx-images: Build and tag one image per configured variant of each
# named service, using the same context and Dockerfile CI uses.
ci-build-helx-images: $(PYTHON_READY)
	$(call require-services)
	@set -euo pipefail; \
	plan=$$($(PYTHON) $(CI_SCRIPT) image-plan $(IMAGE_PLAN_FLAGS)); \
	while IFS=$$'\t' read -r component name reference context dockerfile; do \
		echo "Building $$reference:$(TAG) for $(IMAGE_PLATFORM)"; \
		docker build --platform "$(IMAGE_PLATFORM)" -f "$$dockerfile" -t "$$reference:$(TAG)" "$$context"; \
	done <<< "$$plan"
	@echo 'Next: make ci-load-helx-images or make ci-push-helx-images, with the same SERVICES and TAG$(if $(IMAGE_REGISTRY), and IMAGE_REGISTRY)'

# ci-load-helx-images: Load the built images straight into a local cluster, so
# nothing has to reach a registry.
ci-load-helx-images: $(PYTHON_READY)
	$(call require-services)
	@set -euo pipefail; \
	tool="$(CLUSTER_TOOL)"; \
	if test "$$tool" = auto; then \
		for candidate in kind minikube k3d; do \
			if command -v "$$candidate" >/dev/null 2>&1; then tool="$$candidate"; break; fi; \
		done; \
	fi; \
	if test "$$tool" = auto; then \
		echo "No local cluster tool found. Install kind, minikube, or k3d,"; \
		echo "or use 'make ci-push-helx-images' to push to a registry instead."; \
		exit 1; \
	fi; \
	plan=$$($(PYTHON) $(CI_SCRIPT) image-plan $(IMAGE_PLAN_FLAGS)); \
	while IFS=$$'\t' read -r component name reference context dockerfile; do \
		if ! docker image inspect "$$reference:$(TAG)" >/dev/null 2>&1; then \
			echo "$$reference:$(TAG) has not been built."; \
			echo 'Run: make ci-build-helx-images SERVICES="$(SERVICES)" TAG=$(TAG)$(if $(IMAGE_REGISTRY), IMAGE_REGISTRY=$(IMAGE_REGISTRY))'; \
			exit 1; \
		fi; \
		echo "Loading $$reference:$(TAG) into $$tool"; \
		case "$$tool" in \
			kind) kind load docker-image "$$reference:$(TAG)" $${CLUSTER_NAME:+--name "$(CLUSTER_NAME)"} ;; \
			minikube) minikube image load "$$reference:$(TAG)" ;; \
			k3d) k3d image import "$$reference:$(TAG)" $${CLUSTER_NAME:+-c "$(CLUSTER_NAME)"} ;; \
			*) echo "Unsupported CLUSTER_TOOL: $$tool"; exit 1 ;; \
		esac; \
	done <<< "$$plan"

# ci-push-helx-images: Push the built images to a registry, for a cluster that
# cannot be loaded into directly. Defaults to Harbor, so docker login
# containers.renci.org first, or set IMAGE_REGISTRY to push elsewhere.
ci-push-helx-images: $(PYTHON_READY)
	$(call require-services)
	@set -euo pipefail; \
	plan=$$($(PYTHON) $(CI_SCRIPT) image-plan $(IMAGE_PLAN_FLAGS)); \
	while IFS=$$'\t' read -r component name reference context dockerfile; do \
		if ! docker image inspect "$$reference:$(TAG)" >/dev/null 2>&1; then \
			echo "$$reference:$(TAG) has not been built."; \
			echo 'Run: make ci-build-helx-images SERVICES="$(SERVICES)" TAG=$(TAG)$(if $(IMAGE_REGISTRY), IMAGE_REGISTRY=$(IMAGE_REGISTRY))'; \
			exit 1; \
		fi; \
		echo "Pushing $$reference:$(TAG)"; \
		docker push "$$reference:$(TAG)"; \
	done <<< "$$plan"

##> Then make ci-build-helx-chart, listed above, to package the umbrella
##@ ci Building and inspecting one service
# ci-build-common-chart: Vendor dependencies, lint, and package the shared
# library chart. It lives outside services/, so ci-build-chart cannot reach it.
ci-build-common-chart: $(PYTHON_READY)
	@PYTHON="$(PYTHON)" bash $(BUILD_CHART) "$(COMMON_CHART)"

# ci-build-helx-chart: Package the umbrella chart. Set CHART_CHANNEL to build a
# candidate; CHART_CHANNEL_COMMIT defaults to HEAD.
ci-build-helx-chart: $(PYTHON_READY)
	$(call check-services)
	@channel="$(CHART_CHANNEL)"; \
	services="$(RESOLVED_SERVICES)"; \
	image_tag=""; \
	if test -n "$$services"; then image_tag="$(TAG)"; fi; \
	if test -n "$$services" && test -z "$$channel"; then channel=local; fi; \
	commit="$(CHART_CHANNEL_COMMIT)"; \
	if test -n "$$channel" && test -z "$$commit"; then \
		commit=$$(git rev-parse HEAD); \
	fi; \
	if test -n "$(IMAGE_REGISTRY)" && test -z "$$channel"; then \
		echo "IMAGE_REGISTRY only reaches the chart through an image pin, and"; \
		echo "nothing is pinned here. Add SERVICES=\"a b\" for the services you"; \
		echo "pushed, SERVICES=all if that was all of them, or"; \
		echo "CHART_CHANNEL=<name> to pin every image."; \
		exit 1; \
	fi; \
	if test -n "$$services"; then \
		echo "Pinning $$services to $(TAG)$(if $(IMAGE_REGISTRY), at $(IMAGE_REGISTRY)); every other image stays on its released tag"; \
	fi; \
	PYTHON="$(PYTHON)" CHART_CHANNEL="$$channel" CHART_CHANNEL_COMMIT="$$commit" \
	CHART_CHANNEL_SERVICES="$$services" \
	CHART_IMAGE_TAG="$$image_tag" \
	CHART_IMAGE_REGISTRY="$(IMAGE_REGISTRY)" \
	CHART_PACKAGE_DIR="$(CHART_DIST)" \
		bash $(BUILD_CHART) "$(UMBRELLA_CHART)"
	@echo 'Next: make ci-helm-deploy RELEASE=<name> NAMESPACE=<ns> VALUES="a.yaml b.yaml"'

##@ ci Deploying a local build (see README.md "DevEx")
# ci-helm-deploy: Install or upgrade RELEASE from the archive ci-build-helx-chart
# packaged, found through the pointer that build leaves behind. Values files
# come from LOCAL_VALUES_FILE, then VALUES.
ci-helm-deploy:
	@set -euo pipefail; \
	pointer="$(UMBRELLA_PACKAGE_POINTER)"; \
	if test ! -f "$$pointer"; then \
		echo "No packaged umbrella chart at $$pointer."; \
		echo 'Run: make ci-build-helx-chart'; \
		exit 1; \
	fi; \
	package=$$(cat "$$pointer"); \
	if test ! -f "$$package"; then \
		echo "$$pointer names $$package, which no longer exists."; \
		echo 'Run: make ci-build-helx-chart to package it again.'; \
		exit 1; \
	fi; \
	list="$(LOCAL_VALUES_FILE)"; \
	warnings=0; \
	values_shown=""; \
	values_args=(); \
	if test -f "$$list"; then \
		line_number=0; \
		entries=0; \
		while read -r entry || test -n "$$entry"; do \
			line_number=$$((line_number + 1)); \
			case "$$entry" in ''|'#'*) continue ;; esac; \
			entries=$$((entries + 1)); \
			case "$$entry" in \
				'~') entry="$$HOME" ;; \
				'~/'*) entry="$$HOME/$${entry#'~/'}" ;; \
			esac; \
			if test ! -f "$$entry"; then \
				echo "WARNING: $$list line $$line_number names $$entry, which does not exist."; \
				echo "         That file's values will not reach this release."; \
				warnings=$$((warnings + 1)); \
				continue; \
			fi; \
			values_args+=(--values "$$entry"); \
			values_shown="$$values_shown $$entry"; \
		done < "$$list"; \
		if test "$$entries" -eq 0; then \
			echo "WARNING: $$list names no values files."; \
			echo "         Add one values-file path per line, each relative to the"; \
			echo "         repository root; blank lines and # comments are ignored."; \
			warnings=$$((warnings + 1)); \
		fi; \
	else \
		echo "WARNING: no local values file at $$list."; \
		echo "         Create it there, with one values-file path per line,"; \
		echo "         each relative to the repository root, for example:"; \
		echo "           deploy/local-dev/my-cluster-values.yaml"; \
		echo "           deploy/local-dev/my-secret-values.yaml"; \
		echo "         It is gitignored, so it stays out of the repository."; \
		warnings=$$((warnings + 1)); \
	fi; \
	context=$$(kubectl config current-context 2>/dev/null || echo '<none>'); \
	namespace="$(NAMESPACE)"; \
	if test -z "$$namespace"; then \
		namespace=$$(kubectl config view --minify --output jsonpath='{..namespace}' 2>/dev/null); \
		if test -z "$$namespace"; then \
			echo "No namespace to deploy into: NAMESPACE is unset and context"; \
			echo "$$context selects none. Deploying into 'default' is not assumed."; \
			echo 'Name one for this command:'; \
			echo '  make ci-helm-deploy NAMESPACE=<ns>'; \
			echo 'or set one on the context, for every command that follows:'; \
			echo '  kubectl config set-context --current --namespace=<ns>'; \
			exit 1; \
		fi; \
	fi; \
	echo "Deploying $$package"; \
	echo "  release   $(RELEASE)"; \
	echo "  context   $$context"; \
	echo "  namespace $$namespace"; \
	echo "  values   $${values_shown:- (none)}$(if $(VALUES), $(VALUES))"; \
	if test "$$warnings" -gt 0; then \
		if test -n "$(ASSUME_YES)"; then \
			echo "ASSUME_YES is set; continuing past $$warnings warning(s)."; \
		elif (: < /dev/tty) 2>/dev/null; then \
			printf 'Proceed with the deploy anyway? [y/N] ' > /dev/tty; \
			read -r reply < /dev/tty || reply=''; \
			case "$$reply" in \
				y|Y) ;; \
				*) echo 'Cancelled; nothing was deployed.'; exit 1 ;; \
			esac; \
		else \
			echo 'No terminal to ask on, so cancelling rather than assuming yes.'; \
			echo 'Set ASSUME_YES=1 to deploy past warnings without the prompt.'; \
			exit 1; \
		fi; \
	fi; \
	helm upgrade --install "$(RELEASE)" "$$package" \
		--namespace "$$namespace" --create-namespace \
		$${values_args[@]+"$${values_args[@]}"} \
		$(foreach values_file,$(VALUES),--values "$(values_file)") \
		$(HELM_FLAGS)
##> Exporting TAG is what keeps all four agreeing; left unset it is recomputed from
##> HEAD each command. Unset SERVICES to leave every image on its released tag.

##@ ci Tearing down a release
# ci-uninstall-release RELEASE=<name>: Uninstall RELEASE, then delete the
# storage and credentials helm leaves behind -- UNINSTALL_PVCS and
# UNINSTALL_SECRETS name them, and only the ones that exist are touched.
# Everything is listed for confirmation before anything is deleted. RELEASE has
# to be named explicitly: this deletes data, so the default is not assumed. A
# release that is already gone is not an error, which is what lets this finish a
# teardown that stopped halfway.
ci-uninstall-release:
	@set -euo pipefail; \
	if test '$(origin RELEASE)' = file; then \
		echo 'RELEASE is required, for example: make $@ RELEASE=$(RELEASE)'; \
		echo 'This deletes the release and its data, so no default is assumed.'; \
		exit 1; \
	fi; \
	context=$$(kubectl config current-context 2>/dev/null || echo '<none>'); \
	namespace="$(NAMESPACE)"; \
	if test -z "$$namespace"; then \
		namespace=$$(kubectl config view --minify --output jsonpath='{..namespace}' 2>/dev/null); \
		if test -z "$$namespace"; then \
			echo "No namespace to uninstall from: NAMESPACE is unset and context"; \
			echo "$$context selects none. Uninstalling from 'default' is not assumed."; \
			echo 'Name one for this command:'; \
			echo '  make ci-uninstall-release RELEASE=$(RELEASE) NAMESPACE=<ns>'; \
			echo 'or set one on the context, for every command that follows:'; \
			echo '  kubectl config set-context --current --namespace=<ns>'; \
			exit 1; \
		fi; \
	fi; \
	release_present=yes; \
	if ! helm status "$(RELEASE)" --namespace "$$namespace" >/dev/null 2>&1; then \
		release_present=no; \
	fi; \
	pvcs=(); \
	pvcs_shown=""; \
	for name in $(UNINSTALL_PVCS); do \
		if kubectl get persistentvolumeclaim "$$name" --namespace "$$namespace" >/dev/null 2>&1; then \
			pvcs+=("$$name"); \
			pvcs_shown="$$pvcs_shown $$name"; \
		fi; \
	done; \
	secrets=(); \
	secrets_shown=""; \
	for name in $(UNINSTALL_SECRETS); do \
		if kubectl get secret "$$name" --namespace "$$namespace" >/dev/null 2>&1; then \
			secrets+=("$$name"); \
			secrets_shown="$$secrets_shown $$name"; \
		fi; \
	done; \
	release_shown='installed'; \
	if test "$$release_present" = no; then \
		release_shown='not installed'; \
		if test -n "$$pvcs_shown$$secrets_shown"; then \
			release_shown='not installed; deleting only what it left behind'; \
		fi; \
	fi; \
	echo "Uninstalling $(RELEASE)"; \
	echo "  context   $$context"; \
	echo "  namespace $$namespace"; \
	echo "  release   $$release_shown"; \
	echo "  pvcs     $${pvcs_shown:- (none present)}"; \
	echo "  secrets  $${secrets_shown:- (none present)}"; \
	if test "$$release_present" = no && test -z "$$pvcs_shown$$secrets_shown"; then \
		echo 'Nothing to uninstall or delete.'; \
		exit 0; \
	fi; \
	if test -n "$$pvcs_shown"; then \
		echo 'Deleting those claims destroys the data in them; this cannot be undone.'; \
	fi; \
	if test -n "$(ASSUME_YES)"; then \
		echo 'ASSUME_YES is set; continuing without asking.'; \
	elif (: < /dev/tty) 2>/dev/null; then \
		printf 'Proceed? [y/N] ' > /dev/tty; \
		read -r reply < /dev/tty || reply=''; \
		case "$$reply" in \
			y|Y) ;; \
			*) echo 'Cancelled; nothing was deleted.'; exit 1 ;; \
		esac; \
	else \
		echo 'No terminal to ask on, so cancelling rather than assuming yes.'; \
		echo 'Set ASSUME_YES=1 to uninstall without the prompt.'; \
		exit 1; \
	fi; \
	if test "$$release_present" = yes; then \
		helm uninstall "$(RELEASE)" --namespace "$$namespace"; \
	fi; \
	if test -n "$$pvcs_shown"; then \
		kubectl delete persistentvolumeclaim --namespace "$$namespace" \
			--ignore-not-found $${pvcs[@]+"$${pvcs[@]}"}; \
	fi; \
	if test -n "$$secrets_shown"; then \
		kubectl delete secret --namespace "$$namespace" \
			--ignore-not-found $${secrets[@]+"$${secrets[@]}"}; \
	fi
##> A claim can sit in Terminating until the pods using it are gone; kubectl waits
##> it out. Anything the charts did not create is left alone, PersistentVolumes
##> included -- a Retain volume outlives its claim and is yours to delete.

##@ ci Building and inspecting one service
# docker-build: Build one service image exactly as CI builds it
docker-build:
	$(call require-service)
	@if test ! -f "services/$(SERVICE)/Dockerfile"; then \
		echo "services/$(SERVICE) has no Dockerfile; it is chart-only"; exit 1; \
	fi
	@docker build --platform "$(IMAGE_PLATFORM)" -f "services/$(SERVICE)/Dockerfile" "services/$(SERVICE)"

##@ ci Developer checks (see README.md "DevEx")
# pre-push: Every check CI will run that can run locally
pre-push: ci-tests ci-validate-everything ci-check-versions check-locks
	@git diff --check
	@echo "pre-push checks passed"

# install-hooks: Run pre-push automatically via git hooks
install-hooks:
	@git config core.hooksPath "$(HOOKS_PATH)"
	@echo "core.hooksPath = $(HOOKS_PATH)"
	@echo "Undo with: git config --unset core.hooksPath"

##@ locks Chart.lock maintenance
# sync-locks: Regenerate Chart.lock for every chart that declares dependencies.
# Charts without dependencies are skipped rather than treated as an error.
sync-locks:
	$(call require-pyyaml)
	@$(PYTHON) $(CI_SCRIPT) sync-lock --all

# sync-helx-lock: Regenerate only the umbrella chart's Chart.lock
sync-helx-lock:
	$(call require-pyyaml)
	@$(PYTHON) $(CI_SCRIPT) sync-lock "$(UMBRELLA_CHART)"

# check-locks: Verify every lock matches its Chart.yaml without writing anything
check-locks:
	$(call require-pyyaml)
	@$(PYTHON) $(CI_SCRIPT) sync-lock --all --check
##> Python setup is automatic; run make ci-pip-install to do it explicitly

##@ subtrees Subtree updates
# pull-remotes: Pull every configured service subtree in sequence
pull-remotes: pull-appstore \
	pull-appstore-chart \
	pull-appstore-prepuller \
	pull-appstore-sockets \
	pull-appstore-sockets-chart \
	pull-helx-ldap \
	pull-ldap-sync \
	pull-ui \
	pull-ui-chart \
	pull-user-mutator \
	pull-helx-chart
