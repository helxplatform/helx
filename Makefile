SHELL := /bin/bash

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
CHECK_VERSIONS_FLAGS            ?= --include-untracked
CHANNEL                         ?= develop
SERVICE                         ?=
CHART_CHANNEL                   ?=
CHART_CHANNEL_COMMIT            ?=
HOOKS_PATH                      ?= .githooks

.DEFAULT_GOAL := help

# Every target here mutates the same git repository -- the index lock,
# FETCH_HEAD, and subtree merges are all shared -- so nothing in this file is
# safe to run concurrently. GNU make 3.81 (the make macOS ships) ignores any
# prerequisites given to .NOTPARALLEL and serializes the whole file regardless,
# so this is stated bare: it is exactly what already happens, and it keeps the
# same meaning on make 4.4+, where a prerequisite list would silently narrow it
# to only the listed targets' prerequisites.
.NOTPARALLEL:

.PHONY: help setup add-remotes add-subtrees \
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
        docker-build \
        pre-push \
        install-hooks

#help: Show the available repository setup and subtree tasks
help:
	@echo 'Repository setup:'
	@echo '  make setup          Add all remotes and missing service subtrees'
	@echo '  make add-remotes    Add or verify all subtree remotes'
	@echo '  make add-subtrees   Add all missing service subtrees'
	@echo
	@echo 'Subtree updates:'
	@echo '  make pull-remotes                  Pull all configured service subtrees'
	@echo '  make pull-appstore                 Pull appstore/develop into services/appstore'
	@echo '  make pull-appstore-chart           Pull appstore-chart/main'
	@echo '  make pull-appstore-prepuller       Pull appstore-prepuller/main'
	@echo '  make pull-appstore-sockets         Pull appstore-sockets/master into services/appstore-sockets'
	@echo '  make pull-appstore-sockets-chart   Pull appstore-sockets-chart/master into services/appstore-sockets/chart'
	@echo '  make pull-helx-ldap                Pull helx-ldap/develop into services/helx-ldap'
	@echo '  make pull-ldap-sync                Pull ldap-sync/master into services/ldap-sync'
	@echo '  make pull-ui                       Pull ui/develop into services/ui'
	@echo '  make pull-ui-chart                 Pull ui-chart/master into services/ui/chart'
	@echo '  make pull-user-mutator             Pull user-mutator/master'
	@echo
	@echo 'Vendored charts (mirrored by content, not git subtree):'
	@echo '  make pull-helx-chart               Mirror every chart below'
	@echo '  make pull-resty                    Mirror helx-chart/$(HELX_CHART_BRANCH) charts/resty'
	@echo '  make pull-pod-reaper               Mirror helx-chart/$(HELX_CHART_BRANCH) charts/pod-reaper'
	@echo '  Local edits to these charts are overwritten; FORCE=1 skips the dirty check.'
	@echo
	@echo 'Developer checks (see README.md "DevEx"):'
	@echo '  make ci-pip-install                Create $(VENV) and install CI requirements'
	@echo '  make ci-validate-everything        Validate every chart, lock, .helmignore, and image'
	@echo '  make ci-check-versions             Run the version gate  [BASE, CHECK_VERSIONS_FLAGS]'
	@echo '  make ci-tests                      Run the CI suite unit tests'
	@echo '  make pre-push                      Everything above plus check-locks and whitespace'
	@echo '  make install-hooks                 Run pre-push automatically via git hooks'
	@echo
	@echo 'Building and inspecting one service:'
	@echo '  make ci-build-chart SERVICE=<name>       Vendor deps, lint, package services/<name>/chart'
	@echo '  make ci-locked-deps SERVICE=<name>       Print the resolved dependency tuples for it'
	@echo '  make docker-build SERVICE=<name>         Build the image for that service'
	@echo '  make ci-build-common-chart               Vendor deps, lint, package $(COMMON_CHART)'
	@echo '  make ci-build-helx-chart                 Package the umbrella  [CHART_CHANNEL, CHART_CHANNEL_COMMIT]'
	@echo '  make ci-candidate-version                Print the candidate chart version  [CHANNEL]'
	@echo
	@echo 'Environment variables:'
	@echo '  PYTHON=<path>          Interpreter to use (default $(VENV_PYTHON); skips venv setup)'
	@echo '  VENV=<dir>             Virtualenv location (default .venv)'
	@echo '  SERVICE=<name>         Required by the per-service targets above'
	@echo '  BASE=<ref>             Base revision for ci-check-versions (default develop)'
	@echo '  CHECK_VERSIONS_FLAGS=  Set empty to compare committed revisions only'
	@echo '  CHANNEL=<name>         Candidate channel name (default develop)'
	@echo '  CHART_CHANNEL=<name>   Build the umbrella as a candidate for this channel'
	@echo '  CHART_CHANNEL_COMMIT=  Commit whose images the candidate pins (default HEAD)'
	@echo '  FORCE=1                Let the chart mirrors overwrite uncommitted work'
	@echo
	@echo 'Chart.lock maintenance:'
	@echo '  make sync-locks                    Regenerate every chart lock that has dependencies'
	@echo '  make sync-helx-lock                Regenerate only $(UMBRELLA_CHART)'
	@echo '  make check-locks                   Verify every lock without writing'
	@echo '  Python setup is automatic; run make ci-pip-install to do it explicitly'
	@echo
	@echo 'For another branch or prefix, use:'
	@echo '  make pull-subtree REMOTE=appstore PREFIX=services/appstore BRANCH=develop'

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
	$(call ensure-remote,helx-chart,$(HELX_CHART_URL))

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

# ci-build-common-chart: Vendor dependencies, lint, and package the shared
# library chart. It lives outside services/, so ci-build-chart cannot reach it.
ci-build-common-chart: $(PYTHON_READY)
	@PYTHON="$(PYTHON)" bash $(BUILD_CHART) "$(COMMON_CHART)"

# ci-build-helx-chart: Package the umbrella chart. Set CHART_CHANNEL to build a
# candidate; CHART_CHANNEL_COMMIT defaults to HEAD.
ci-build-helx-chart: $(PYTHON_READY)
	@commit="$(CHART_CHANNEL_COMMIT)"; \
	if test -n "$(CHART_CHANNEL)" && test -z "$$commit"; then \
		commit=$$(git rev-parse HEAD); \
		echo "CHART_CHANNEL_COMMIT defaulted to $$commit"; \
	fi; \
	PYTHON="$(PYTHON)" CHART_CHANNEL="$(CHART_CHANNEL)" CHART_CHANNEL_COMMIT="$$commit" \
		bash $(BUILD_CHART) "$(UMBRELLA_CHART)"

# docker-build: Build one service image exactly as CI builds it
docker-build:
	$(call require-service)
	@if test ! -f "services/$(SERVICE)/Dockerfile"; then \
		echo "services/$(SERVICE) has no Dockerfile; it is chart-only"; exit 1; \
	fi
	@docker build -f "services/$(SERVICE)/Dockerfile" "services/$(SERVICE)"

# pre-push: Every check CI will run that can run locally
pre-push: ci-tests ci-validate-everything ci-check-versions check-locks
	@git diff --check
	@echo "pre-push checks passed"

# install-hooks: Point git at $(HOOKS_PATH) so pre-push runs automatically
install-hooks:
	@git config core.hooksPath "$(HOOKS_PATH)"
	@echo "core.hooksPath = $(HOOKS_PATH)"
	@echo "Undo with: git config --unset core.hooksPath"

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
