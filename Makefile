# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

.PHONY: login ling_scripts lint_dockers lint help

login: ## Login to Docker Hub
	docker login --username=$(DOCKER_USER)

lint_scripts: ## Lint shellscripts
	find . -not -path '*/\.*' \
		-exec /bin/bash -c '[ $$(file -b --mime-type {}) == "text/x-shellscript" ]' /bin/bash '{}' ';' \
		-print \
        | xargs docker run --rm -v $$(PWD):/mnt linter shellcheck -x -Calways

lint_dockers: ## Lint Dockerfiles
	find . -type f -name "Dockerfile"
    | xargs docker run --rm -v $(PWD):/mnt linter hadolint \
        --ignore DL3002 \
        --ignore DL3003 \
        --ignore DL3007 \
        --ignore DL3008 \
        --ignore DL3013 \
        --ignore DL3018 \
        --ignore DL4001

lint: lint_scripts lint_dockers

help: ## Show this help message.
	@echo 'Usage: make [command] ...'
	@echo
	@echo "Available commands:"
	@grep -E "^(.+)\:\ ##\ (.+)" ${MAKEFILE_LIST} | column -t -c 2 -s ":#"

default: build
