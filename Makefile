SHELL := /bin/bash

# Git remotes used by the services/ git subtrees.
APPSTORE_URL          ?= https://github.com/helxplatform/appstore.git
APPSTORE_SOCKETS_URL  ?= https://github.com/helxplatform/appstore-sockets.git
UI_URL                ?= https://github.com/helxplatform/helx-ui.git
HELX_LDAP_URL         ?= https://github.com/helxplatform/helx-ldap.git
LDAP_SYNC_URL         ?= https://github.com/helxplatform/ldap-sync.git
APPSTORE_PREPULLER_URL ?= https://github.com/helxplatform/appstore-prepuller.git
USER_MUTATOR_URL      ?= https://github.com/helxplatform/user-mutator.git
APPSTORE_CHART_URL          ?= https://github.com/helxplatform/appstore-chart.git
APPSTORE_SOCKETS_CHART_URL  ?= https://github.com/helxplatform/appstore-sockets-chart.git
UI_CHART_URL                ?= https://github.com/helxplatform/ui-chart.git

# Branches and prefixes used when the subtrees are added or pulled.
APPSTORE_PREFIX           ?= services/appstore
APPSTORE_BRANCH           ?= develop
APPSTORE_SOCKETS_PREFIX   ?= services/appstore-sockets
APPSTORE_SOCKETS_BRANCH   ?= master
UI_PREFIX                 ?= services/ui
UI_BRANCH                 ?= develop
HELX_LDAP_PREFIX          ?= services/helx-ldap
HELX_LDAP_BRANCH          ?= develop
LDAP_SYNC_PREFIX          ?= services/ldap-sync
LDAP_SYNC_BRANCH          ?= master
APPSTORE_PREPULLER_PREFIX ?= services/appstore-prepuller
APPSTORE_PREPULLER_BRANCH ?= main
USER_MUTATOR_PREFIX       ?= services/user-mutator
USER_MUTATOR_BRANCH       ?= master
APPSTORE_CHART_PREFIX          ?= services/appstore/chart
APPSTORE_CHART_BRANCH          ?= main
APPSTORE_SOCKETS_CHART_PREFIX  ?= services/appstore-sockets/chart
APPSTORE_SOCKETS_CHART_BRANCH  ?= master
UI_CHART_PREFIX                ?= services/ui/chart
UI_CHART_BRANCH                ?= master

.DEFAULT_GOAL := help

.PHONY: help setup add-remotes add-subtrees \
        add-subtree-appstore add-subtree-appstore-sockets add-subtree-ui \
        add-subtree-helx-ldap add-subtree-ldap-sync \
        add-subtree-appstore-prepuller add-subtree-user-mutator \
        add-subtree-appstore-chart add-subtree-appstore-sockets-chart \
        add-subtree-ui-chart pull-appstore pull-appstore-sockets \
        pull-appstore-sockets-chart pull-ui pull-helx-ldap pull-ldap-sync \
        pull-appstore-prepuller pull-user-mutator \
        pull-appstore-chart pull-ui-chart pull-remotes pull-subtree

#help: Show the available repository setup and subtree tasks
help:
	@echo 'Repository setup:'
	@echo '  make setup          Add all remotes and missing service subtrees'
	@echo '  make add-remotes    Add or verify all subtree remotes'
	@echo '  make add-subtrees   Add all missing service subtrees'
	@echo
	@echo 'Subtree updates:'
	@echo '  make pull-remotes            Pull all configured service subtrees'
	@echo '  make pull-appstore           Pull appstore/develop into services/appstore'
	@echo '  make pull-appstore-sockets   Pull appstore-sockets/master into services/appstore-sockets'
	@echo '  make pull-appstore-sockets-chart Pull appstore-sockets-chart/master into services/appstore-sockets/chart'
	@echo '  make pull-ui                 Pull ui/develop into services/ui'
	@echo '  make pull-helx-ldap          Pull helx-ldap/develop into services/helx-ldap'
	@echo '  make pull-ldap-sync          Pull ldap-sync/master into services/ldap-sync'
	@echo '  make pull-appstore-prepuller Pull appstore-prepuller/main'
	@echo '  make pull-user-mutator       Pull user-mutator/master'
	@echo '  make pull-appstore-chart     Pull appstore-chart/main'
	@echo '  make pull-ui-chart           Pull ui-chart/master into services/ui/chart'
	@echo
	@echo 'For another branch or prefix, use:'
	@echo '  make pull-subtree REMOTE=appstore PREFIX=services/appstore BRANCH=develop'

# setup: Add all remotes and missing service subtrees
setup: add-subtrees

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

# add-remotes: Add or verify all remotes needed by the service subtrees
add-remotes:
	$(call ensure-remote,appstore,$(APPSTORE_URL))
	$(call ensure-remote,appstore-sockets,$(APPSTORE_SOCKETS_URL))
	$(call ensure-remote,ui,$(UI_URL))
	$(call ensure-remote,helx-ldap,$(HELX_LDAP_URL))
	$(call ensure-remote,ldap-sync,$(LDAP_SYNC_URL))
	$(call ensure-remote,appstore-prepuller,$(APPSTORE_PREPULLER_URL))
	$(call ensure-remote,user-mutator,$(USER_MUTATOR_URL))
	$(call ensure-remote,appstore-chart,$(APPSTORE_CHART_URL))
	$(call ensure-remote,appstore-sockets-chart,$(APPSTORE_SOCKETS_CHART_URL))
	$(call ensure-remote,ui-chart,$(UI_CHART_URL))

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
	add-subtree-appstore-sockets \
	add-subtree-appstore-sockets-chart \
	add-subtree-ui \
	add-subtree-helx-ldap \
	add-subtree-ldap-sync \
	add-subtree-appstore-prepuller \
	add-subtree-user-mutator \
	add-subtree-appstore-chart \
	add-subtree-ui-chart

# add-subtree-appstore: Add the appstore subtree
add-subtree-appstore: add-remotes
	$(call add-subtree,$(APPSTORE_PREFIX),appstore,$(APPSTORE_BRANCH))

# add-subtree-appstore-sockets: Add the appstore-sockets subtree
add-subtree-appstore-sockets: add-remotes
	$(call add-subtree,$(APPSTORE_SOCKETS_PREFIX),appstore-sockets,$(APPSTORE_SOCKETS_BRANCH))

# add-subtree-appstore-sockets-chart: Add the appstore-sockets Helm chart subtree
add-subtree-appstore-sockets-chart: add-remotes
	$(call add-subtree,$(APPSTORE_SOCKETS_CHART_PREFIX),appstore-sockets-chart,$(APPSTORE_SOCKETS_CHART_BRANCH))

# add-subtree-ui: Add the UI subtree
add-subtree-ui: add-remotes
	$(call add-subtree,$(UI_PREFIX),ui,$(UI_BRANCH))

# add-subtree-helx-ldap: Add the helx-ldap subtree
add-subtree-helx-ldap: add-remotes
	$(call add-subtree,$(HELX_LDAP_PREFIX),helx-ldap,$(HELX_LDAP_BRANCH))

# add-subtree-ldap-sync: Add the ldap-sync subtree
add-subtree-ldap-sync: add-remotes
	$(call add-subtree,$(LDAP_SYNC_PREFIX),ldap-sync,$(LDAP_SYNC_BRANCH))

# add-subtree-appstore-prepuller: Add the appstore-prepuller subtree
add-subtree-appstore-prepuller: add-remotes
	$(call add-subtree,$(APPSTORE_PREPULLER_PREFIX),appstore-prepuller,$(APPSTORE_PREPULLER_BRANCH))

# add-subtree-user-mutator: Add the user-mutator subtree
add-subtree-user-mutator: add-remotes
	$(call add-subtree,$(USER_MUTATOR_PREFIX),user-mutator,$(USER_MUTATOR_BRANCH))

# add-subtree-appstore-chart: Add the appstore Helm chart subtree.
add-subtree-appstore-chart: add-remotes
	$(call add-subtree,$(APPSTORE_CHART_PREFIX),appstore-chart,$(APPSTORE_CHART_BRANCH))

# add-subtree-ui-chart: Add the UI Helm chart subtree
add-subtree-ui-chart: add-remotes
	$(call add-subtree,$(UI_CHART_PREFIX),ui-chart,$(UI_CHART_BRANCH))

# pull-subtree: Pull one subtree using REMOTE, PREFIX, and BRANCH variables.
pull-subtree: add-remotes
	@if test -z "$(REMOTE)" || test -z "$(PREFIX)" || test -z "$(BRANCH)"; then \
		echo "Usage: make pull-subtree REMOTE=<remote> PREFIX=<path> BRANCH=<branch>"; \
		exit 1; \
	fi
	git subtree pull --prefix="$(PREFIX)" "$(REMOTE)" "$(BRANCH)"

# pull-appstore: Pull the latest configured appstore branch into its subtree
pull-appstore: add-remotes
	git subtree pull --prefix="$(APPSTORE_PREFIX)" appstore "$(APPSTORE_BRANCH)"

# pull-appstore-sockets: Pull the latest configured appstore-sockets branch
pull-appstore-sockets: add-remotes
	git subtree pull --prefix="$(APPSTORE_SOCKETS_PREFIX)" appstore-sockets "$(APPSTORE_SOCKETS_BRANCH)"

# pull-appstore-sockets-chart: Pull the latest configured appstore-sockets chart branch
pull-appstore-sockets-chart: add-remotes
	git subtree pull --prefix="$(APPSTORE_SOCKETS_CHART_PREFIX)" appstore-sockets-chart "$(APPSTORE_SOCKETS_CHART_BRANCH)"

# pull-ui: Pull the latest configured UI branch into its subtree
pull-ui: add-remotes
	git subtree pull --prefix="$(UI_PREFIX)" ui "$(UI_BRANCH)"

# pull-helx-ldap: Pull the latest configured helx-ldap branch into its subtree
pull-helx-ldap: add-remotes
	git subtree pull --prefix="$(HELX_LDAP_PREFIX)" helx-ldap "$(HELX_LDAP_BRANCH)"

# pull-ldap-sync: Pull the latest configured ldap-sync branch
pull-ldap-sync: add-remotes
	git subtree pull --prefix="$(LDAP_SYNC_PREFIX)" ldap-sync "$(LDAP_SYNC_BRANCH)"

# pull-appstore-prepuller: Pull the latest configured appstore-prepuller branch
pull-appstore-prepuller: add-remotes
	git subtree pull --prefix="$(APPSTORE_PREPULLER_PREFIX)" appstore-prepuller "$(APPSTORE_PREPULLER_BRANCH)"

# pull-user-mutator: Pull the latest configured user-mutator branch
pull-user-mutator: add-remotes
	git subtree pull --prefix="$(USER_MUTATOR_PREFIX)" user-mutator "$(USER_MUTATOR_BRANCH)"

# pull-appstore-chart: Pull the latest configured appstore chart branch
pull-appstore-chart: add-remotes
	git subtree pull --prefix="$(APPSTORE_CHART_PREFIX)" appstore-chart "$(APPSTORE_CHART_BRANCH)"

# pull-ui-chart: Pull the latest configured UI chart branch
pull-ui-chart: add-remotes
	git subtree pull --prefix="$(UI_CHART_PREFIX)" ui-chart "$(UI_CHART_BRANCH)"

# pull-remotes: Pull every configured service subtree in sequence
.NOTPARALLEL: pull-remotes
pull-remotes: pull-appstore \
	pull-appstore-sockets \
	pull-appstore-sockets-chart \
	pull-ui \
	pull-helx-ldap \
	pull-ldap-sync \
	pull-appstore-prepuller \
	pull-user-mutator \
	pull-appstore-chart \
	pull-ui-chart
